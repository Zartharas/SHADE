#!/usr/bin/env python3
"""
eval_harness.py
Expanded evaluation harness for Project SHADE's DLP redaction layer
(dlp_redact.py, paper Section 5.2).

WHAT THIS MEASURES, PRECISELY: precision/recall/F1 of the four regex
patterns in dlp_redact.PATTERNS against a purpose-built, structurally
varied SYNTHETIC benchmark set with per-item ground-truth labels
(this module's own dataset generator, seeded for reproducibility, no
Faker output reused from generate_synthetic_data.py). This is internal
consistency against the pipeline's OWN synthetic ground truth. It is
NOT a measurement of real-world detection accuracy, and does not
imply anything about performance on real text, real PII formats, or
adversarial/obfuscated input. See docs/benchmark.md for the full
scoping statement.

WHY ONLY THE DLP LAYER: this is the only SHADE component that behaves
like a classifier (pattern present / not present, checked against
independently-labeled ground truth). governance_score.py is a
deterministic total function verified by exhaustive enumeration
(verify_policy.py) -- precision/recall doesn't apply to it, since there
is no "wrong" classification possible once the matrix is verified
complete and well-formed, only a "wrong" policy design choice, which is
not something this codebase can self-validate. discovery_scan.py reads
a pre-generated ground-truth label rather than performing independent
detection, so scoring it against that same label would be circular.

Usage:
    python eval_harness.py --n 300 --seed 42 --out experiments/output/dlp_benchmark_report.json
"""
import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shade.dlp_redact import redact_text

# ---------------------------------------------------------------------------
# Benchmark dataset generator: structurally varied synthetic sentences with
# explicit per-pattern-type ground truth. Deliberately includes near-miss
# "distractor" text that looks superficially similar to a pattern but should
# NOT match (to catch false positives) and multiple structural variants of
# each true-positive pattern type (to catch false negatives from format
# variation the original 4-example test in test_pipeline.py never exercised).
# ---------------------------------------------------------------------------

FILLER = [
    "Please review the attached notes before the sync.",
    "The quarterly summary is still in draft form.",
    "Let me know if the timeline needs to shift.",
    "Attaching the updated file for reference.",
    "This section covers the background context only.",
]

EMAIL_TRUE_POSITIVES = [
    "contact me at jane.doe@example.com for details",
    "reach out via first.last+work@sub.example.org",
    "my address is a1@example.co",
    "send it to research.team@university.example.edu",
]
EMAIL_NEAR_MISS = [
    "the @ symbol is used here without an email",
    "meet me at the coffee shop around noon",
    "version 2.0 @ build 445",
]

PHONE_TRUE_POSITIVES = [
    "call 555-123-4567 for support",
    "reach us at (555) 987 6543 anytime",
    "dial +1 555.234.5678 during business hours",
    "phone: 5551239876 works too",
]
PHONE_NEAR_MISS = [
    "order number 45-6789 was shipped yesterday",
    "the meeting room is 123 on floor 4",
    "invoice total came to 4567.89 dollars",
]

SSN_TRUE_POSITIVES = [
    "ssn on file: 123-45-6789",
    "verification number 987-65-4321 was provided",
    "recorded as 456-78-9012 in the old system",
]
SSN_NEAR_MISS = [
    "zip+4 code is 12345-6789 for that branch",  # wrong digit grouping, should not match \d{3}-\d{2}-\d{4}
    "tracking id A123-45-B789 was scanned",       # letters break the pure-digit pattern
    "raw nine digit id 123456789 with no dashes",  # pattern requires dashes, correctly a negative
]

APIKEY_TRUE_POSITIVES = [
    "here is a key sk-fake-AbCdEfGhIjKlMnOpQrStUvWx for testing",
    "rotate this one too: sk-fake-1234567890abcdefGHIJKLMNOP",
]
APIKEY_NEAR_MISS = [
    "short token sk-fake-ABC123 is too short to be a real key shape",
    "unrelated prefix pk-live-AbCdEfGhIjKlMnOpQrStUvWx should not match",
]


def build_benchmark_dataset(n, seed):
    """
    Builds n labeled samples. Each sample is (text, ground_truth) where
    ground_truth is a dict {pattern_label: True/False} for whether that
    pattern type is genuinely present (by construction) in the text.
    Deterministic for a given seed, so the reported metrics are
    reproducible across runs/machines (see docs/benchmark.md).
    """
    rng = random.Random(seed)
    pattern_labels = ["email", "phone", "ssn_shaped", "fake_api_key"]
    pools = {
        "email": (EMAIL_TRUE_POSITIVES, EMAIL_NEAR_MISS),
        "phone": (PHONE_TRUE_POSITIVES, PHONE_NEAR_MISS),
        "ssn_shaped": (SSN_TRUE_POSITIVES, SSN_NEAR_MISS),
        "fake_api_key": (APIKEY_TRUE_POSITIVES, APIKEY_NEAR_MISS),
    }

    samples = []
    for i in range(n):
        choice = rng.random()
        if choice < 0.55:
            # A true-positive fragment for one pattern type, embedded in filler.
            label = rng.choice(pattern_labels)
            tp_pool, _ = pools[label]
            fragment = rng.choice(tp_pool)
            text = f"{rng.choice(FILLER)} {fragment}"
            gt = {p: (p == label) for p in pattern_labels}
        elif choice < 0.85:
            # A near-miss distractor: should NOT trigger its look-alike pattern.
            label = rng.choice(pattern_labels)
            _, nm_pool = pools[label]
            fragment = rng.choice(nm_pool)
            text = f"{rng.choice(FILLER)} {fragment}"
            gt = {p: False for p in pattern_labels}
        else:
            # Clean text: no pattern of any type.
            text = " ".join(rng.sample(FILLER, k=2))
            gt = {p: False for p in pattern_labels}
        samples.append({"id": i, "text": text, "ground_truth": gt})
    return samples


def score(samples):
    """
    Runs redact_text on each sample and computes per-pattern-type
    precision/recall/F1 plus overall micro-averaged metrics, using the
    ground truth attached at dataset-build time (not derived from the
    detector itself, so this is an independent check).
    """
    pattern_labels = ["email", "phone", "ssn_shaped", "fake_api_key"]
    counts = {p: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for p in pattern_labels}

    for sample in samples:
        _, hits = redact_text(sample["text"])
        detected = set(hits.keys())
        for p in pattern_labels:
            truth = sample["ground_truth"][p]
            found = p in detected
            if truth and found:
                counts[p]["tp"] += 1
            elif truth and not found:
                counts[p]["fn"] += 1
            elif not truth and found:
                counts[p]["fp"] += 1
            else:
                counts[p]["tn"] += 1

    per_pattern = {}
    total_tp = total_fp = total_fn = 0
    for p, c in counts.items():
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and (precision + recall) > 0
            else None
        )
        per_pattern[p] = {
            "tp": tp, "fp": fp, "fn": fn, "tn": c["tn"],
            "precision": round(precision, 3) if precision is not None else None,
            "recall": round(recall, 3) if recall is not None else None,
            "f1": round(f1, 3) if f1 is not None else None,
        }
        total_tp += tp
        total_fp += fp
        total_fn += fn

    micro_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else None
    micro_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else None
    micro_f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if micro_precision is not None and micro_recall is not None and (micro_precision + micro_recall) > 0
        else None
    )

    return {
        "n_samples": len(samples),
        "per_pattern": per_pattern,
        "micro_avg": {
            "precision": round(micro_precision, 3) if micro_precision is not None else None,
            "recall": round(micro_recall, 3) if micro_recall is not None else None,
            "f1": round(micro_f1, 3) if micro_f1 is not None else None,
        },
        "scope_note": (
            "Measures dlp_redact.py's four regex patterns against this "
            "module's own synthetic, structurally-varied benchmark set with "
            "programmatically-assigned ground truth. This is internal "
            "consistency against synthetic ground truth, NOT a real-world "
            "detection accuracy estimate. See docs/benchmark.md."
        ),
    }


def run(n=300, seed=42, out_path=None):
    samples = build_benchmark_dataset(n, seed)
    report = score(samples)
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
    return report


def main():
    ap = argparse.ArgumentParser(description="DLP evaluation harness: precision/recall/F1 against synthetic ground truth.")
    ap.add_argument("--n", type=int, default=300, help="number of benchmark samples to generate")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility")
    ap.add_argument("--out", type=str, default="experiments/output/dlp_benchmark_report.json")
    args = ap.parse_args()

    report = run(n=args.n, seed=args.seed, out_path=args.out)
    print(f"DLP benchmark: {report['n_samples']} samples, seed={args.seed}")
    print(json.dumps(report["micro_avg"], indent=2))
    for p, m in report["per_pattern"].items():
        print(f"  {p}: precision={m['precision']} recall={m['recall']} f1={m['f1']} "
              f"(tp={m['tp']} fp={m['fp']} fn={m['fn']} tn={m['tn']})")
    print(f"Report -> {args.out}")


if __name__ == "__main__":
    main()
