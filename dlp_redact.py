#!/usr/bin/env python3
"""
dlp_redact.py
Phase 3 of Project SHADE, see paper Section 8.3 / 5.2.

Lightweight, dependency-free re-implementation of the DLP redaction pattern
used by production tools cited in the paper (aidlp / llmproxy, which combine
static pattern matching -- FlashText-style -- with ML entity recognition via
Microsoft Presidio/spaCy). This script uses regex-based static pattern
matching ONLY, against the synthetic ground truth injected by
generate_synthetic_data.py. The resulting trigger rate reflects this
script's four configured expressions against data from the same generator;
it is not a measured precision/recall/F1 estimate and should not be treated
as one (see paper Section 8.6).

In PRODUCTION, a contextual or ML-based recognizer such as Presidio could be
added to address regex's known under-detection of context-dependent PII.
Whether that materially improves recall would need to be measured
separately against representative, independently annotated data -- it
should not be assumed. See paper Section 5.2.

Usage:
    python dlp_redact.py --in output/synthetic_usage.csv --out output/redacted_events.csv --report output/redaction_report.json
"""
import argparse
import csv
import json
import os
import re

PATTERNS = {
    "fake_api_key": re.compile(r"\bsk-fake-[A-Za-z0-9_-]{20,40}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "ssn_shaped": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "phone": re.compile(r"\b(?:\+?\d{1,2}[-.\s])?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
}


def redact_text(text):
    redacted = text
    hits = {}
    for label, pattern in PATTERNS.items():
        matches = pattern.findall(redacted)
        if matches:
            hits[label] = len(matches)
            redacted = pattern.sub(f"[REDACTED:{label.upper()}]", redacted)
    return redacted, hits


def redact_events(rows):
    """
    Mutates each row in-place, adding redacted_prompt_text/redaction_hits,
    and returns the aggregate report dict. Shared by the CLI main() below
    and run_pipeline.py so the redaction logic exists in exactly one place.
    """
    triggered = 0
    hits_total = {}
    for row in rows:
        redacted, hits = redact_text(row["prompt_text"])
        row["redacted_prompt_text"] = redacted
        row["redaction_hits"] = json.dumps(hits)
        if hits:
            triggered += 1
            for k, v in hits.items():
                hits_total[k] = hits_total.get(k, 0) + v

    total = len(rows)
    return {
        "total_events": total,
        "events_with_sensitive_pattern_detected": triggered,
        "redaction_trigger_rate_pct": round(100 * triggered / total, 1) if total else 0,
        "hits_by_pattern_type": hits_total,
        "note": (
            "Regex-only static matching against synthetic data from the same "
            "generator; not a precision/recall/F1 estimate. Production "
            "deployments could add Presidio/spaCy ML-based entity recognition "
            "(see paper Section 5.2), but any recall improvement should be "
            "measured against independently annotated data, not assumed."
        ),
    }


def main():
    ap = argparse.ArgumentParser(description="DLP layer: detect and redact synthetic sensitive patterns.")
    ap.add_argument("--in", dest="infile", type=str, default="output/synthetic_usage.csv")
    ap.add_argument("--out", type=str, default="output/redacted_events.csv")
    ap.add_argument("--report", type=str, default="output/redaction_report.json")
    args = ap.parse_args()

    with open(args.infile, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames + ["redacted_prompt_text", "redaction_hits"]

    report = redact_events(rows)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    with open(args.report, "w") as f:
        json.dump(report, f, indent=2)

    print(f"DLP scan complete: sensitive pattern detected in {report['events_with_sensitive_pattern_detected']}/"
          f"{report['total_events']} events ({report['redaction_trigger_rate_pct']}%).")
    print(f"Redacted events -> {args.out}")
    print(f"Report -> {args.report}")


if __name__ == "__main__":
    main()
