#!/usr/bin/env python3
"""
shade/governance_score.py
Phase 4 of Project SHADE, see paper Section 8.4 / 4.4.

Implements the classification taxonomy's decision matrix (paper Section 4.4)
as executable logic: combines tool_risk x data_sensitivity into one of five
governance actions via a deterministic lookup table (governance decisioning,
not a numerical or probabilistic risk score). This is not a stand-in for
ML-judge governance tools such as GovLLM, which use a fundamentally
different evaluation approach; it is a deliberately simple, rule-based
implementation so the mapping from policy table to code is auditable
line-by-line, which the paper's compliance-mapping section (Section 7)
argues is a prerequisite for any claim of regulatory alignment.

The matrix is formally verified for completeness and non-conflict in
verify_policy.py (see docs/adr/0001-formal-verification-of-governance-matrix.md
for the method and why it is sufficient for a 3x3 table).

Usage:
    python3 shade/governance_score.py --in output/synthetic_usage.csv --out output/governance_report.json
"""
import argparse
import csv
import json
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# Mirrors the decision matrix in paper Section 4.4.
DECISION_MATRIX = {
    ("high", "critical"): "BLOCK",
    ("high", "sensitive"): "BLOCK_WITH_OVERRIDE",
    ("high", "public"): "ALLOW",
    ("medium", "critical"): "REDACT_THEN_ALLOW",
    ("medium", "sensitive"): "ALLOW_WITH_MONITORING",
    ("medium", "public"): "ALLOW",
    ("low", "critical"): "REDACT_THEN_ALLOW",
    ("low", "sensitive"): "ALLOW_WITH_MONITORING",
    ("low", "public"): "ALLOW",
}

# Short, human-readable justification for each matrix cell. Kept as a
# separate table (rather than generated from the action name) so the wording
# is explicit and reviewable on its own, the same way the action mapping is.
DECISION_REASONS = {
    ("high", "critical"): "blocked: high tool risk + critical data sensitivity",
    ("high", "sensitive"): "blocked pending override: high tool risk + sensitive data",
    ("high", "public"): "allowed: high tool risk but only public data involved",
    ("medium", "critical"): "redact-then-allow: medium tool risk + critical data sensitivity",
    ("medium", "sensitive"): "allowed with monitoring: medium tool risk + sensitive data",
    ("medium", "public"): "allowed: medium tool risk, public data",
    ("low", "critical"): "redact-then-allow: low tool risk but critical data sensitivity",
    ("low", "sensitive"): "allowed with monitoring: low tool risk + sensitive data",
    ("low", "public"): "allowed: low tool risk, public data",
}

FALLBACK_ACTION = "ALLOW_WITH_MONITORING"
FALLBACK_REASON = (
    "allowed with monitoring: no explicit matrix rule for this combination "
    "(fallback path -- see verify_policy.py, this should never trigger for "
    "the 9 documented tool_risk/data_sensitivity combinations)"
)


def decide(tool_risk, data_sensitivity):
    """Original signature, preserved for backward compatibility: returns
    only the action string. Prefer decide_with_reason() for new code."""
    return DECISION_MATRIX.get((tool_risk, data_sensitivity), FALLBACK_ACTION)


def decide_with_reason(tool_risk, data_sensitivity):
    """Returns (action, reason) so every decision is self-explanatory,
    not just a bare label. Reason strings are the DECISION_REASONS entry
    for known cells, or FALLBACK_REASON if the combination isn't in the
    matrix (which verify_policy.py asserts cannot happen for the 9
    documented combinations)."""
    key = (tool_risk, data_sensitivity)
    if key in DECISION_MATRIX:
        return DECISION_MATRIX[key], DECISION_REASONS[key]
    return FALLBACK_ACTION, FALLBACK_REASON


@dataclass
class AppealRequest:
    """
    Documented interface for what an appeal/exception-request workflow
    would look like on top of the governance decision matrix. This is a
    STUB: it models the shape of the request/response and where it would
    plug into score_events(), but does not implement routing, storage,
    approval logic, or notifications. Left here so the interface is
    designed and reviewable now, without committing to a specific
    ticketing/workflow backend before one is chosen.

    Intended flow (not implemented):
      1. A BLOCK or BLOCK_WITH_OVERRIDE decision surfaces an AppealRequest
         to the affected user/team, pre-filled with the triggering event
         and its decision + reason.
      2. requester submits `justification` and the request is routed to an
         approver (owner TBD -- likely the data/tool owner named in
         config/known_endpoints.yaml, not a fixed role).
      3. approver sets `status` to "approved" or "denied" and optionally
         `approver_note`; approvals should be time-bounded and scoped to
         the specific event/tool/data combination, not a blanket override
         of the matrix cell.
      4. Approved appeals would need to be logged as an auditable exception
         list, separate from and without mutating DECISION_MATRIX itself --
         the matrix should stay the single source of truth for the default
         policy; approved appeals are documented, time-bounded deviations
         from it, not edits to it.
    """
    event_id: str
    tool_risk: str
    data_sensitivity: str
    original_action: str
    original_reason: str
    justification: Optional[str] = None
    status: str = "pending"  # pending | approved | denied
    approver_note: Optional[str] = None
    requested_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def score_events(rows):
    """
    Mutates each row in-place with governance_action and governance_reason,
    returns the aggregate report dict. Shared by the CLI main() below and
    run_pipeline.py.
    """
    action_counts = Counter()
    for row in rows:
        action, reason = decide_with_reason(row["tool_risk"], row["data_sensitivity"])
        row["governance_action"] = action
        row["governance_reason"] = reason
        action_counts[action] += 1

    total = len(rows)
    return {
        "total_events_scored": total,
        "action_distribution": dict(action_counts),
        "action_distribution_pct": {
            k: round(100 * v / total, 1) for k, v in action_counts.items()
        } if total else {},
        "blocked_or_override_pct": round(
            100 * (action_counts.get("BLOCK", 0) + action_counts.get("BLOCK_WITH_OVERRIDE", 0)) / total, 1
        ) if total else 0,
    }


def main():
    ap = argparse.ArgumentParser(description="Governance layer: score events against the Section 4.4 decision matrix.")
    ap.add_argument("--in", dest="infile", type=str, default="output/synthetic_usage.csv")
    ap.add_argument("--out", type=str, default="output/governance_report.json")
    ap.add_argument("--events_out", type=str, default="output/scored_events.csv")
    args = ap.parse_args()

    with open(args.infile, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames + ["governance_action", "governance_reason"]

    report = score_events(rows)

    os.makedirs(os.path.dirname(args.events_out) or ".", exist_ok=True)
    with open(args.events_out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Governance scoring complete for {report['total_events_scored']} events.")
    print(json.dumps(report["action_distribution_pct"], indent=2))
    print(f"Scored events -> {args.events_out}")
    print(f"Report -> {args.out}")


if __name__ == "__main__":
    main()
