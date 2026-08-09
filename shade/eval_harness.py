#!/usr/bin/env python3
"""
shade/eval_harness.py
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

STATISTICAL UNCERTAINTY: a point estimate like "F1 = 1.0" says nothing
about how much evidence backs it -- 0 errors in 10 samples and 0 errors
in 10,000 samples are very different claims. This module reports Wilson
score confidence intervals (Wilson, 1927 -- chosen over the naive normal
approximation specifically because it stays well-behaved at the 0%/100%
boundary, which is exactly where these benchmarks tend to land) for
precision and recall, since both are directly observed proportions
(successes/trials). F1 is a nonlinear function of precision and recall
with no simple closed-form interval, so its interval is estimated by
nonparametric bootstrap (resampling the scored items with replacement,
fixed seed for reproducibility) instead of assumed away. None of this
changes what is or isn't being measured (see above) -- it only makes
explicit how much a given point estimate should be trusted given the
sample size used to produce it.

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
    python3 shade/eval_harness.py --n 300 --seed 42 --out experiments/output/dlp_benchmark_report.json
"""
import argparse
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shade.dlp_redact import redact_text

# ---------------------------------------------------------------------------
# Statistical uncertainty: Wilson score interval for a directly-observed
# proportion (precision, recall), and a nonparametric bootstrap for F1
# (which has no simple closed-form interval since it's a nonlinear
# function of two proportions). See this module's docstring for why
# Wilson over the naive normal approximation.
# ---------------------------------------------------------------------------
Z_95 = 1.959963984540054  # two-sided 95% normal quantile, the standard constant every stats textbook uses -- no scipy dependency needed for this one value.


def wilson_ci(successes, trials, z=Z_95):
    """Wilson score interval for a binomial proportion. Returns (lower,
    upper), both rounded to 3 decimals, or (None, None) if trials == 0
    (undefined -- no observations to bound)."""
    if trials == 0:
        return None, None
    p_hat = successes / trials
    denom = 1 + z**2 / trials
    center = (p_hat + z**2 / (2 * trials)) / denom
    margin = (z * math.sqrt((p_hat * (1 - p_hat) / trials) + (z**2 / (4 * trials**2)))) / denom
    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    return round(lower, 3), round(upper, 3)


def f1_wilson_plugin_ci(precision_ci, recall_ci):
    """
    Conservative F1 interval via monotonic plug-in: F1(p, r) = 2pr/(p+r)
    is increasing in both p and r (holding the other fixed), so evaluating
    it at (p_lower, r_lower) and (p_upper, r_upper) gives valid, if not
    exact, bounds -- it ignores the joint correlation between precision's
    and recall's estimation errors, so it's typically a bit wider than a
    true joint interval, but that conservatism is the safe direction to
    err in.

    This exists specifically because bootstrap_f1_ci() below degenerates
    to zero width whenever the observed sample has zero errors: every
    resample of an all-correct sample is also all-correct, so the
    bootstrap distribution has no variance to report -- exactly the case
    (a perfect observed score) where an F1 interval is most needed and
    most informative. Wilson's interval doesn't have this problem (it's a
    closed-form function of n and the observed count, not a resample of
    the data), so plugging Wilson bounds through F1's formula gives a
    genuine non-degenerate interval in that case.
    """
    p_lo, p_hi = precision_ci
    r_lo, r_hi = recall_ci
    if None in (p_lo, p_hi, r_lo, r_hi):
        return None, None

    def _f1(p, r):
        return round(2 * p * r / (p + r), 3) if (p + r) > 0 else 0.0

    return _f1(p_lo, r_lo), _f1(p_hi, r_hi)


def bootstrap_f1_ci(per_sample_rows, seed, n_bootstrap=1000, z_ignore=None):
    """
    Nonparametric bootstrap CI for micro-averaged F1: resample the scored
    items (with replacement, same size as the original set) n_bootstrap
    times, recompute micro F1 on each resample from its own tp/fp/fn
    counts, and take the 2.5th/97.5th percentiles as a 95% CI. Resampling
    happens at the ITEM level (each item's already-computed per-pattern
    tp/fp/fn/tn classification), not by re-running redact_text, so this
    is cheap even at n_bootstrap=1000 and reflects genuine sampling
    variability in which items happened to be drawn, not detector noise
    (the detector itself is deterministic).
    """
    rng = random.Random(seed)
    n = len(per_sample_rows)
    if n == 0:
        return None, None
    f1_samples = []
    for _ in range(n_bootstrap):
        resample = [per_sample_rows[rng.randrange(n)] for _ in range(n)]
        tp = sum(r["tp"] for r in resample)
        fp = sum(r["fp"] for r in resample)
        fn = sum(r["fn"] for r in resample)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        f1_samples.append(f1)
    f1_samples.sort()
    lower_idx = int(0.025 * n_bootstrap)
    upper_idx = min(n_bootstrap - 1, int(0.975 * n_bootstrap))
    return round(f1_samples[lower_idx], 3), round(f1_samples[upper_idx], 3)


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


# ---------------------------------------------------------------------------
# HARD TIER: a second, deliberately harder benchmark, built to actually
# surface the recall gaps docs/benchmark.md's "scope" section has stated
# as a limitation since this harness was first written -- OCR-noise-shaped
# text, Unicode homoglyphs, deliberately obfuscated PII, and non-US
# formats. This is NOT gated by a pass/fail threshold in
# tests/test_pipeline.py the way the easy tier is: it is diagnostic, not a
# regression gate, because failing to catch some of these is the expected,
# honest, and more informative result -- the point is to measure and
# report the actual boundary, not to keep raising a bar until it's cleared.
#
# Every fragment below is a genuine true positive (it IS PII of the
# labeled type) by construction; there are no near-miss distractors in
# this tier (scoped out deliberately -- the easy tier already demonstrates
# the patterns don't false-positive on lookalikes; this tier's whole point
# is recall against harder true positives, not precision).
#
# Each category's expected outcome was empirically checked against the
# actual PATTERNS regexes before being included here (not assumed) --
# some genuinely surprising results came out of that check and are noted
# inline; see docs/benchmark.md's "Harder benchmark tier" section for the
# full, measured write-up.
# ---------------------------------------------------------------------------

# OCR noise: common OCR digit/letter confusions (0<->O, 1<->l/I) applied to
# otherwise-valid phone/SSN/API-key shapes. Empirically: none of these are
# detected by the current regexes (the confused character falls outside
# \d or the exact expected character class).
OCR_NOISE_TRUE_POSITIVES = {
    "phone": [
        "call 555-l23-4567 for support",       # '1' -> 'l'
        "reach us at 555-123-456O anytime",    # '0' -> 'O'
    ],
    "ssn_shaped": [
        "ssn on file: l23-45-6789",            # '1' -> 'l'
        "recorded as 456-78-90l2 previously",  # '1' -> 'l'
    ],
    "fake_api_key": [
        # Genuine 'O'->'0' OCR-style substitution. Empirically STILL
        # detected -- unlike phone/SSN's narrow \d-only patterns, the API
        # key charclass [A-Za-z0-9_-] already includes both the original
        # and the OCR-confused character, so this particular noise type
        # cannot break this particular pattern by construction. Included
        # deliberately (not dropped) to make that asymmetry visible in the
        # results rather than only showing categories that fail uniformly.
        "here is a key sk-fake-AbCdEfGhIjKlMn0pQrStUvWx for testing",
    ],
}

# Unicode homoglyphs: a visually-identical non-ASCII character substituted
# into an email address. Empirically: a homoglyph in the DOMAIN is never
# detected (the domain char-class run breaks and there's no fallback);
# a homoglyph in the LOCAL PART is detected only if a punctuation
# character (a genuine \w/\W boundary) follows it before the rest of
# the local part -- a homoglyph immediately followed by more letters
# (no intervening punctuation) is NOT detected. All three variants are
# included specifically because this nuance is easy to get wrong by
# assumption rather than measurement.
HOMOGLYPH_TRUE_POSITIVES = {
    "email": [
        "contact me at jane.doe@exаmple.com please",   # Cyrillic 'a' in domain -- NOT detected
        "contact me at jаne.doe@example.com please",   # Cyrillic 'a' in local part, dot follows -- IS detected (partial match after the punctuation boundary)
        "contact me at jаne@example.com now",          # Cyrillic 'a' in local part, no punctuation follows -- NOT detected
    ],
}

# Deliberately obfuscated PII: spelled-out or heavily spaced, the kind a
# human reader parses instantly but a fixed-shape regex cannot. Empirically:
# none of these are detected.
OBFUSCATED_TRUE_POSITIVES = {
    "email": [
        "reach me at jane dot doe at example dot com thanks",
        "reach me at jane . doe @ example . com thanks",
    ],
    "phone": [
        "call five five five, one two three, four five six seven",
    ],
    "ssn_shaped": [
        "ssn on file: 1 2 3 - 4 5 - 6 7 8 9",
    ],
    "fake_api_key": [
        "here is a key sk-fake-AbCd EfGh IjKl MnOp QrSt UvWx for testing",
    ],
}

# International / non-US formats: the existing patterns were authored
# against US phone shape (\d{3}-\d{3}-\d{4} with optional country code)
# and US SSN shape (\d{3}-\d{2}-\d{4}) specifically -- see docs/benchmark.md's
# long-standing scope note. Empirically: none of these are detected.
INTERNATIONAL_TRUE_POSITIVES = {
    "phone": [
        "call +44 20 7946 0958 for support",     # UK
        "call +91 98765 43210 for support",      # India
    ],
    "ssn_shaped": [
        # UK National Insurance number -- closest real-world equivalent to
        # a US SSN as a personal government ID; mapped to ssn_shaped ground
        # truth as a deliberate stretch, documented rather than silent.
        "national insurance number QQ123456C on file",
    ],
}

# Fullwidth Unicode digits: included because it's a genuine POSITIVE
# surprise, not another gap -- Python's \d in default (Unicode) mode
# matches Unicode decimal-digit characters, not just ASCII 0-9, so a
# fullwidth-digit phone/SSN is actually caught. Worth measuring and
# reporting precisely because assuming "non-ASCII digits must fail" would
# have been wrong.
FULLWIDTH_DIGIT_TRUE_POSITIVES = {
    "phone": [
        "call \uff15\uff15\uff15-\uff11\uff12\uff13-\uff14\uff15\uff16\uff17 for support",
    ],
    "ssn_shaped": [
        "ssn on file: \uff11\uff12\uff13-\uff14\uff15-\uff16\uff17\uff18\uff19",
    ],
}

HARD_TIER_CATEGORIES = {
    "ocr_noise": OCR_NOISE_TRUE_POSITIVES,
    "unicode_homoglyph": HOMOGLYPH_TRUE_POSITIVES,
    "obfuscated": OBFUSCATED_TRUE_POSITIVES,
    "international_format": INTERNATIONAL_TRUE_POSITIVES,
    "fullwidth_digit": FULLWIDTH_DIGIT_TRUE_POSITIVES,
}


def build_hard_benchmark_dataset():
    """
    Builds the full, fixed hard-tier dataset (every fragment above, once
    each -- unlike the easy tier, this isn't randomly sampled with a
    seed/n, since the whole set is small and hand-curated; every fragment
    is independently meaningful evidence, not a statistical sample from a
    larger population). Returns the same {id, text, ground_truth} shape as
    build_benchmark_dataset(), plus a "hard_category" field per sample so
    results can be broken down by failure mode, not just by pattern type.
    """
    pattern_labels = ["email", "phone", "ssn_shaped", "fake_api_key"]
    samples = []
    i = 0
    for category, per_pattern_fragments in HARD_TIER_CATEGORIES.items():
        for label, fragments in per_pattern_fragments.items():
            for fragment in fragments:
                gt = {p: (p == label) for p in pattern_labels}
                samples.append({
                    "id": i, "text": fragment, "ground_truth": gt,
                    "hard_category": category,
                })
                i += 1
    return samples


def score_hard_tier(samples):
    """
    Scores the hard-tier dataset the same way score() scores the easy
    tier (same redact_text() call, same tp/fp/fn/tn bookkeeping, same
    Wilson interval), but additionally breaks recall down by
    hard_category, since which categories fail is the actually
    informative output here, not just an aggregate number. No F1
    bootstrap is computed for this tier: with a small, fixed (not
    randomly sampled) dataset, resampling it doesn't estimate sampling
    variability over a larger population the way it does for the
    randomly-generated easy tier -- there is no larger population being
    sampled from, so a bootstrap CI here would imply more than the design
    supports.
    """
    pattern_labels = ["email", "phone", "ssn_shaped", "fake_api_key"]
    by_category = {}

    for sample in samples:
        _, hits = redact_text(sample["text"])
        detected = set(hits.keys())
        category = sample["hard_category"]
        by_category.setdefault(category, {"tp": 0, "fn": 0, "examples": []})
        for p in pattern_labels:
            truth = sample["ground_truth"][p]
            if not truth:
                continue  # this tier has no near-miss distractors; only score real positives
            found = p in detected
            if found:
                by_category[category]["tp"] += 1
            else:
                by_category[category]["fn"] += 1
            by_category[category]["examples"].append({
                "text": sample["text"], "pattern": p, "detected": found,
            })

    category_results = {}
    total_tp = total_fn = 0
    for category, c in by_category.items():
        tp, fn = c["tp"], c["fn"]
        recall = tp / (tp + fn) if (tp + fn) else None
        category_results[category] = {
            "tp": tp, "fn": fn, "n": tp + fn,
            "recall": round(recall, 3) if recall is not None else None,
            "recall_ci_95": list(wilson_ci(tp, tp + fn)) if (tp + fn) else [None, None],
            "examples": c["examples"],
        }
        total_tp += tp
        total_fn += fn

    overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else None
    return {
        "n_samples": len(samples),
        "by_category": category_results,
        "overall_recall": round(overall_recall, 3) if overall_recall is not None else None,
        "overall_recall_ci_95": list(wilson_ci(total_tp, total_tp + total_fn)) if (total_tp + total_fn) else [None, None],
        "scope_note": (
            "Diagnostic hard tier: a small, hand-curated (not randomly "
            "sampled) set of genuine PII fragments designed to probe OCR "
            "noise, Unicode homoglyphs, deliberate obfuscation, "
            "international formats, and fullwidth digits against the "
            "existing four regex patterns. Recall gaps here are the "
            "EXPECTED, honest result for a regex-only detector authored "
            "against US-centric, clean-format examples -- see "
            "docs/benchmark.md's \"Harder benchmark tier\" section. This "
            "is not gated by a pass/fail threshold in "
            "tests/test_pipeline.py; it is measured and reported, not "
            "enforced."
        ),
    }


def score(samples, ci_seed=42, n_bootstrap=1000):
    """
    Runs redact_text on each sample and computes per-pattern-type
    precision/recall/F1 plus overall micro-averaged metrics, using the
    ground truth attached at dataset-build time (not derived from the
    detector itself, so this is an independent check). Also computes a
    95% Wilson score interval for every precision/recall value (including
    per-pattern) and a 95% bootstrap interval for every F1 value -- see
    this module's docstring and wilson_ci()/bootstrap_f1_ci() above for
    why two different methods are used for the two kinds of quantity.
    """
    pattern_labels = ["email", "phone", "ssn_shaped", "fake_api_key"]
    counts = {p: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for p in pattern_labels}
    # One row per SAMPLE (not per sample-pattern-pair), totaling tp/fp/fn
    # across that sample's 4 pattern judgments. This is the correct unit
    # to bootstrap over: a sample's 4 pattern judgments are correlated by
    # construction (they come from the same generated text), so resampling
    # whole samples preserves that structure; resampling individual
    # sample-pattern pairs would treat them as independent and understate
    # the true interval width.
    per_sample_rows = []

    for sample in samples:
        _, hits = redact_text(sample["text"])
        detected = set(hits.keys())
        row = {"tp": 0, "fp": 0, "fn": 0}
        for p in pattern_labels:
            truth = sample["ground_truth"][p]
            found = p in detected
            if truth and found:
                counts[p]["tp"] += 1
                row["tp"] += 1
            elif truth and not found:
                counts[p]["fn"] += 1
                row["fn"] += 1
            elif not truth and found:
                counts[p]["fp"] += 1
                row["fp"] += 1
            else:
                counts[p]["tn"] += 1
        per_sample_rows.append(row)

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
        precision_ci = wilson_ci(tp, tp + fp) if (tp + fp) else (None, None)
        recall_ci = wilson_ci(tp, tp + fn) if (tp + fn) else (None, None)
        per_pattern[p] = {
            "tp": tp, "fp": fp, "fn": fn, "tn": c["tn"],
            "precision": round(precision, 3) if precision is not None else None,
            "precision_ci_95": list(precision_ci),
            "recall": round(recall, 3) if recall is not None else None,
            "recall_ci_95": list(recall_ci),
            "f1": round(f1, 3) if f1 is not None else None,
            "f1_ci_95_wilson_plugin": list(f1_wilson_plugin_ci(precision_ci, recall_ci)),
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
    micro_precision_ci = wilson_ci(total_tp, total_tp + total_fp) if (total_tp + total_fp) else (None, None)
    micro_recall_ci = wilson_ci(total_tp, total_tp + total_fn) if (total_tp + total_fn) else (None, None)
    micro_f1_ci = bootstrap_f1_ci(per_sample_rows, seed=ci_seed, n_bootstrap=n_bootstrap)
    micro_f1_ci_wilson_plugin = f1_wilson_plugin_ci(micro_precision_ci, micro_recall_ci)

    return {
        "n_samples": len(samples),
        "per_pattern": per_pattern,
        "micro_avg": {
            "precision": round(micro_precision, 3) if micro_precision is not None else None,
            "precision_ci_95": list(micro_precision_ci),
            "recall": round(micro_recall, 3) if micro_recall is not None else None,
            "recall_ci_95": list(micro_recall_ci),
            "f1": round(micro_f1, 3) if micro_f1 is not None else None,
            "f1_ci_95": list(micro_f1_ci),
            "f1_ci_95_wilson_plugin": list(micro_f1_ci_wilson_plugin),
        },
        "ci_methodology": (
            "precision_ci_95 / recall_ci_95: Wilson score interval (exact "
            "closed form for a binomial proportion, well-behaved at the "
            "0-percent/100-percent boundary). f1_ci_95: nonparametric "
            f"bootstrap, n_bootstrap={n_bootstrap}, resampling whole scored "
            "items (not individual pattern judgments) with replacement, "
            f"seed={ci_seed} for reproducibility -- NOTE this degenerates to "
            "zero width whenever the observed sample has zero errors (every "
            "resample of an all-correct sample is also all-correct), which "
            "is exactly the case this benchmark usually lands in. "
            "f1_ci_95_wilson_plugin: F1's formula evaluated at the Wilson "
            "bounds of precision and recall -- conservative (ignores the "
            "correlation between precision's and recall's errors) but "
            "non-degenerate even at a perfect observed score, so treat this "
            "one as the more informative F1 interval when f1_ci_95 shows "
            "[1.0, 1.0]. All intervals are 95 percent two-sided. A "
            "[None, None] interval means the denominator was zero (e.g. no "
            "ground-truth positives for that pattern in this sample) and "
            "the interval is undefined, not zero-width."
        ),
        "scope_note": (
            "Measures dlp_redact.py's four regex patterns against this "
            "module's own synthetic, structurally-varied benchmark set with "
            "programmatically-assigned ground truth. This is internal "
            "consistency against synthetic ground truth, NOT a real-world "
            "detection accuracy estimate. Confidence intervals quantify "
            "sampling uncertainty given n_samples; they do NOT widen the "
            "scope of what is being measured -- see docs/benchmark.md."
        ),
    }


def run(n=300, seed=42, out_path=None, n_bootstrap=1000):
    samples = build_benchmark_dataset(n, seed)
    # Reuse the dataset seed for the bootstrap RNG too -- one seed fully
    # determines this function's output, keeping "seed=42" sufficient to
    # reproduce a report byte-for-byte, rather than needing a second
    # seed parameter threaded through every caller.
    report = score(samples, ci_seed=seed, n_bootstrap=n_bootstrap)
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
    return report


def run_hard_tier(out_path=None):
    samples = build_hard_benchmark_dataset()
    report = score_hard_tier(samples)
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
    return report


def main():
    ap = argparse.ArgumentParser(description="DLP evaluation harness: precision/recall/F1 against synthetic ground truth, with 95% confidence intervals.")
    ap.add_argument("--n", type=int, default=300, help="number of benchmark samples to generate (easy tier only)")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility (also seeds the F1 bootstrap; easy tier only)")
    ap.add_argument("--n_bootstrap", type=int, default=1000, help="number of bootstrap resamples for the F1 confidence interval (easy tier only)")
    ap.add_argument("--tier", type=str, choices=["easy", "hard"], default="easy",
                     help="'easy' (default): the randomly-generated, CI-gated benchmark this harness has always run. "
                          "'hard': a small, fixed, diagnostic set probing OCR noise, Unicode homoglyphs, obfuscation, "
                          "international formats, and fullwidth digits -- NOT gated by a threshold, see "
                          "docs/benchmark.md's 'Harder benchmark tier' section.")
    ap.add_argument("--out", type=str, default=None,
                     help="defaults to experiments/output/dlp_benchmark_report.json (easy tier) or "
                          "experiments/output/dlp_hard_tier_report.json (hard tier)")
    args = ap.parse_args()

    if args.tier == "hard":
        out_path = args.out or "experiments/output/dlp_hard_tier_report.json"
        report = run_hard_tier(out_path=out_path)
        print(f"DLP hard tier: {report['n_samples']} hand-curated fragments (diagnostic, not threshold-gated)")
        print(f"  overall recall: {report['overall_recall']} {report['overall_recall_ci_95']}")
        for category, cm in report["by_category"].items():
            print(f"  {category}: recall={cm['recall']} {cm['recall_ci_95']} (tp={cm['tp']} fn={cm['fn']} n={cm['n']})")
        print(f"Report -> {out_path}")
        return

    out_path = args.out or "experiments/output/dlp_benchmark_report.json"
    report = run(n=args.n, seed=args.seed, out_path=out_path, n_bootstrap=args.n_bootstrap)
    print(f"DLP benchmark: {report['n_samples']} samples, seed={args.seed}")
    m = report["micro_avg"]
    print(f"  micro-avg: precision={m['precision']} {m['precision_ci_95']}  "
          f"recall={m['recall']} {m['recall_ci_95']}  f1={m['f1']} "
          f"bootstrap-CI={m['f1_ci_95']} wilson-plugin-CI={m['f1_ci_95_wilson_plugin']}")
    for p, pm in report["per_pattern"].items():
        print(f"  {p}: precision={pm['precision']} {pm['precision_ci_95']}  "
              f"recall={pm['recall']} {pm['recall_ci_95']}  f1={pm['f1']} "
              f"wilson-plugin-CI={pm['f1_ci_95_wilson_plugin']} "
              f"(tp={pm['tp']} fp={pm['fp']} fn={pm['fn']} tn={pm['tn']})")
    print(f"Report -> {out_path}")


if __name__ == "__main__":
    main()
