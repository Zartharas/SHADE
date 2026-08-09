#!/usr/bin/env python3
"""
shade/dp_aggregate_reporting.py

Scoped privacy-preserving prototype: applies (epsilon)-differential
privacy to SHADE's AGGREGATE reporting outputs (governance action
distribution, department-level breakdowns), not to the per-event
classification step itself.

WHY AGGREGATE REPORTING, NOT THE CLASSIFICATION STEP -- A SCOPING
DECISION, STATED EXPLICITLY: shade/governance_score.py's per-event decide() is a
deterministic lookup over a verified, complete decision table (ADR 0001);
there's no statistical query there to add DP noise to -- every event gets
exactly the action the (verified, auditable) matrix specifies, and adding
noise to that specific step would either do nothing meaningful or actively
undermine the auditability property Phase 1 of this project spent effort
establishing. The place a privacy mechanism actually has something to do
is where SHADE aggregates events into reported counts (e.g. "12 BLOCK
events in Finance this week") -- publishing exact small-group counts like
that can itself leak information about specific individuals' activity,
which is the classic motivating case for differentially private count/
histogram release (Dwork & Roth's canonical formulation). This module
targets that step instead of forcing DP onto a step where it doesn't
fit -- a deliberate reinterpretation of "differential privacy on the
classification step" from the original scoping conversation, documented
here rather than silently done.

METHOD: the Laplace mechanism for count queries -- add Laplace-distributed
noise with scale = sensitivity/epsilon to each released count, where
sensitivity=1 (adding or removing one synthetic event changes any given
count by at most 1). This is a standard, well-understood DP mechanism
(Dwork & Roth, 2014, "The Algorithmic Foundations of Differential
Privacy"), not a novel contribution -- the contribution here, such as it
is, is applying it to SHADE's specific reporting outputs and being honest
about the resulting utility cost.

LIMITATIONS, STATED RATHER THAN IGNORED:
- Composition is now handled at two levels (see
  docs/adr/0005-dp-privacy-budget-composition.md for the full writeup and
  the accounting bug this closes):
  (1) WITHIN one privatize_report() call, which makes TWO releases from
  the same underlying rows (action distribution, department
  distribution). Per basic/sequential composition (Dwork & Roth, 2014,
  Theorem 3.16), releasing two epsilon-DP results from the same data
  costs 2*epsilon total, not epsilon -- so `epsilon` here is now the
  TOTAL budget for the whole report, split evenly (epsilon/2 each) across
  the two releases. Before ADR 0005, both releases silently spent the
  full nominal epsilon each, so a caller passing epsilon=1.0 actually
  received a report that cost 2.0 epsilon while the output only ever
  reported "epsilon: 1.0" -- a real, previously unfixed under-statement
  of privacy cost, not a hypothetical one.
  (2) ACROSS multiple privatize_report() calls against overlapping data
  (e.g. releasing today's report, then tomorrow's, from data that
  overlaps), via the new `PrivacyBudgetTracker` class, which a caller can
  optionally pass to accumulate and cap total spend across several calls.
  It fails CLOSED (raises before computing an over-budget release), but
  it only tracks what it is explicitly given -- there is still no
  persistent, cross-invocation ledger (e.g. surviving separate `python3
  shade/run_pipeline.py` runs on different days). That would need a
  state file on disk and is flagged as future work in ADR 0005, not
  attempted here.
- Only count/histogram queries are covered (Laplace mechanism). This does
  not extend to more complex statistics, and does not implement any
  DP-SGD-style training mechanism or federated learning -- the original
  scoping conversation's other listed option, not attempted here (picking
  both would have violated the "at most one, properly scoped" rule this
  project set for itself).
- Operates on 100% synthetic Faker-generated data, same as the rest of
  this repository. The privacy GUARANTEE is real (the Laplace mechanism's
  formal DP property holds regardless of whether the underlying data is
  synthetic), but there is no real sensitive data here for it to protect
  in this demo -- the point is to prototype and measure the mechanism's
  utility cost, not to claim an actual deployment's data is protected.

Usage (standalone, generates its own synthetic run):
    python shade/dp_aggregate_reporting.py --n 2000 --epsilons 0.1,0.5,1.0,5.0

Graduated into shade/ per docs/adr/0004-integrating-dp-aggregate-reporting.md.
See that ADR for how shade/run_pipeline.py's opt-in
--privatize_governance_report flag calls privatize_report() directly on
the SAME already-scored events that pipeline run produced -- a tighter
integration than this module's own standalone main() (below), which
generates a fresh, separate synthetic run to privatize when invoked on
its own.
"""
import argparse
import json
import math
import os
import random
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shade.generate_synthetic_data import generate as generate_events
from shade.governance_score import score_events


def laplace_noise(scale, rng):
    """Samples from Laplace(0, scale) using inverse-CDF sampling (stdlib
    random only, no numpy dependency needed for this)."""
    u = rng.random() - 0.5
    return -scale * math.copysign(1, u) * math.log(1 - 2 * abs(u)) if u != 0 else 0.0


def privatize_counts(true_counts, epsilon, sensitivity=1, rng=None):
    """
    Applies the Laplace mechanism to each count in true_counts (a dict of
    category -> integer count). Returns a dict of category -> noisy,
    non-negative, rounded count. sensitivity=1 is correct for counting
    queries where one event's presence/absence changes any single
    category's count by at most 1 (true here: each synthetic event
    contributes to exactly one category per breakdown).
    """
    rng = rng or random.Random()
    scale = sensitivity / epsilon
    noisy = {}
    for category, true_count in true_counts.items():
        noise = laplace_noise(scale, rng)
        noisy[category] = max(0, round(true_count + noise))
    return noisy


def mean_absolute_error(true_counts, noisy_counts):
    keys = set(true_counts) | set(noisy_counts)
    if not keys:
        return 0.0
    return sum(abs(true_counts.get(k, 0) - noisy_counts.get(k, 0)) for k in keys) / len(keys)


class PrivacyBudgetExceededError(Exception):
    """Raised by PrivacyBudgetTracker.spend() when a release would push
    cumulative epsilon spend past the tracker's total_budget. Raised
    BEFORE the release is computed -- the caller never gets a noisy
    result that secretly cost more privacy than the budget allows."""


class PrivacyBudgetTracker:
    """
    Tracks cumulative epsilon spend across multiple DP releases made
    against the same (or overlapping) underlying dataset, using basic /
    sequential composition (Dwork & Roth, 2014, Theorem 3.16): the total
    privacy loss of several epsilon_i-DP releases is bounded by
    sum(epsilon_i). This is the simplest composition bound that is
    actually correct -- not an advanced or moments-accountant-style
    composition, which would be more sample-efficient (a smaller total
    epsilon for the same number of releases) but is real over-engineering
    for a prototype expected to make a handful of releases per dataset,
    the same "simplest method that is correct at the actual scale"
    reasoning ADR 0001 applied when choosing brute-force verification
    over an SMT solver for the governance matrix.

    Fails CLOSED: spend() raises PrivacyBudgetExceededError BEFORE a
    release that would exceed the budget is computed, rather than
    computing it and warning afterward -- the same pattern this
    project's other guardrails already follow (shade/verify_policy.py's
    verify_arbitrary_matrix(), shade/policy_proposer.py's formal
    verification gate): the check actually blocks the bad case instead
    of just documenting that it shouldn't happen.

    Deliberately NOT persisted across process invocations -- this
    tracker's lifetime is whatever the caller's Python process keeps it
    alive for. A real deployment releasing reports from separate
    `python3 shade/run_pipeline.py` invocations over time would need a
    durable ledger (e.g. a state file read/written on each run); that is
    explicitly out of scope here -- see
    docs/adr/0005-dp-privacy-budget-composition.md.
    """

    def __init__(self, total_budget):
        if total_budget <= 0:
            raise ValueError("total_budget must be positive")
        self.total_budget = total_budget
        self.spent = 0.0
        self.history = []  # list of {"label", "epsilon", "cumulative_after"}

    def remaining(self):
        return self.total_budget - self.spent

    def spend(self, epsilon, label=None):
        if epsilon <= 0:
            raise ValueError("epsilon must be positive")
        prospective_total = self.spent + epsilon
        # Small float tolerance so exactly-at-budget spends (e.g. two
        # releases of exactly total_budget/2 each) aren't rejected due to
        # floating-point rounding.
        if prospective_total > self.total_budget + 1e-9:
            raise PrivacyBudgetExceededError(
                f"Release '{label or '<unlabeled>'}' at epsilon={epsilon} would bring "
                f"cumulative spend to {prospective_total} against a total budget of "
                f"{self.total_budget} (already spent: {self.spent}, remaining: "
                f"{self.remaining()}). Rejected before computing the release -- see "
                f"docs/adr/0005-dp-privacy-budget-composition.md."
            )
        self.spent = prospective_total
        self.history.append({"label": label, "epsilon": epsilon, "cumulative_after": self.spent})
        return self.spent


def privatize_report(rows, epsilon, seed=42, budget_tracker=None, label=None):
    """
    Privatizes two aggregate breakdowns from a scored event set: governance
    action distribution, and department-level event counts. Returns both
    the true and noisy versions plus the utility cost (MAE) for
    transparency -- a real deployment would release ONLY the noisy
    version; both are shown here for this prototype's own evaluation.

    `epsilon` is the TOTAL privacy budget for this report (both releases
    combined), NOT the per-release epsilon. Because the two releases
    (action distribution, department distribution) are computed from the
    same underlying `rows`, basic composition means their combined cost is
    the SUM of their individual epsilons -- so each release actually uses
    epsilon/2, keeping the report's total cost equal to the `epsilon`
    the caller asked to spend. See docs/adr/0005-dp-privacy-budget-composition.md
    for why this changed from an earlier version where both releases each
    spent the full nominal epsilon (silently costing 2*epsilon total).

    If `budget_tracker` (a PrivacyBudgetTracker) is given, this report's
    total epsilon is recorded against it BEFORE either release is
    computed; PrivacyBudgetExceededError propagates if it would exceed
    that tracker's remaining budget, and no noise is generated in that
    case.
    """
    if budget_tracker is not None:
        budget_tracker.spend(epsilon, label=label)

    per_query_epsilon = epsilon / 2
    rng = random.Random(seed)

    true_action_counts = dict(Counter(r["governance_action"] for r in rows))
    true_dept_counts = dict(Counter(r["department"] for r in rows))

    noisy_action_counts = privatize_counts(true_action_counts, per_query_epsilon, rng=rng)
    noisy_dept_counts = privatize_counts(true_dept_counts, per_query_epsilon, rng=rng)

    result = {
        "total_epsilon": epsilon,
        "per_query_epsilon": per_query_epsilon,
        "composition_note": (
            f"epsilon={epsilon} is the TOTAL budget for this report's two releases "
            f"combined; each release (action_distribution, department_distribution) "
            f"individually uses per_query_epsilon={per_query_epsilon}, so their "
            f"summed cost under basic composition equals the total epsilon requested. "
            f"See docs/adr/0005-dp-privacy-budget-composition.md."
        ),
        "action_distribution": {
            "true": true_action_counts,
            "dp_released": noisy_action_counts,
            "mean_absolute_error": round(mean_absolute_error(true_action_counts, noisy_action_counts), 2),
        },
        "department_distribution": {
            "true": true_dept_counts,
            "dp_released": noisy_dept_counts,
            "mean_absolute_error": round(mean_absolute_error(true_dept_counts, noisy_dept_counts), 2),
        },
    }
    if budget_tracker is not None:
        result["budget_tracker_state"] = {
            "spent": budget_tracker.spent,
            "remaining": budget_tracker.remaining(),
            "total_budget": budget_tracker.total_budget,
        }
    return result


def run_epsilon_sweep(rows, epsilons, seed=42):
    """Evaluates utility cost (MAE) across several epsilon values so the
    privacy/utility trade-off is visible, not just asserted."""
    results = []
    for eps in epsilons:
        r = privatize_report(rows, eps, seed=seed)
        results.append({
            "epsilon": eps,
            "action_distribution_mae": r["action_distribution"]["mean_absolute_error"],
            "department_distribution_mae": r["department_distribution"]["mean_absolute_error"],
        })
    return results


def main():
    ap = argparse.ArgumentParser(description="Differentially private aggregate reporting prototype (Laplace mechanism, count queries only).")
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--epsilons", type=str, default="0.1,0.5,1.0,5.0",
                     help="Comma-separated TOTAL per-report epsilon budgets to evaluate "
                          "(each value is split epsilon/2 across the two releases inside "
                          "one report -- see docs/adr/0005-dp-privacy-budget-composition.md).")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=str, default="output/dp_report.json")
    ap.add_argument("--budget_cap", type=float, default=None,
                     help="Optional demo of PrivacyBudgetTracker: if given, the single "
                          "detail-at-median-epsilon report below is spent against a "
                          "tracker with this total_budget, and the report includes the "
                          "tracker's resulting state. Does NOT apply to --epsilons sweep "
                          "(that sweep evaluates hypothetical alternative epsilon choices, "
                          "only one of which would actually be deployed -- composing all "
                          "swept values would misrepresent that as several real releases).")
    args = ap.parse_args()

    epsilons = [float(x) for x in args.epsilons.split(",")]

    rows = generate_events(args.n, "config/known_endpoints.yaml", seed=args.seed)
    score_events(rows)  # adds governance_action/governance_reason in place

    median_epsilon = epsilons[len(epsilons) // 2]
    tracker = PrivacyBudgetTracker(args.budget_cap) if args.budget_cap is not None else None
    detail = privatize_report(rows, epsilon=median_epsilon, seed=args.seed,
                               budget_tracker=tracker, label="detail_at_median_epsilon")
    sweep = run_epsilon_sweep(rows, epsilons, seed=args.seed)

    result = {
        "n_events": len(rows),
        "epsilon_sweep": sweep,
        "detail_at_median_epsilon": detail,
        "scope_note": (
            "Laplace mechanism applied to aggregate count/histogram queries "
            "over governance_action and department, computed from 100% "
            "synthetic Faker-generated events. Each epsilon value above is a TOTAL "
            "per-report budget, split epsilon/2 across the report's two releases "
            "(basic composition) -- see docs/adr/0005-dp-privacy-budget-composition.md. "
            "Cross-report composition is available via PrivacyBudgetTracker "
            "(--budget_cap demonstrates it for the single detail report above) but is "
            "not persisted across separate process invocations -- see that ADR's "
            "stated limitations. Not federated learning, not DP-SGD training."
        ),
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Privacy/utility sweep across TOTAL per-report epsilon={epsilons} (lower = more privacy, more noise):")
    for row in sweep:
        print(f"  total_epsilon={row['epsilon']}: action_dist MAE={row['action_distribution_mae']}, "
              f"dept_dist MAE={row['department_distribution_mae']}")
    if tracker is not None:
        print(f"Budget tracker: spent={tracker.spent} / total_budget={tracker.total_budget} "
              f"(remaining={tracker.remaining()})")
    print(f"Report -> {args.out}")


if __name__ == "__main__":
    main()
