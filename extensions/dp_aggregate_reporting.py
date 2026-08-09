#!/usr/bin/env python3
"""
extensions/dp_aggregate_reporting.py

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
- No privacy BUDGET COMPOSITION tracking across multiple releases. Each
  call to privatize_report() spends a fresh epsilon as if it were the only
  query ever made against the dataset. Releasing several differently-sliced
  aggregates (by department, by tool, by action) from the same underlying
  events consumes cumulative privacy budget in a real deployment (basic
  composition: total epsilon = sum of per-query epsilons); this prototype
  does not implement that accounting. A real deployment would need it.
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

Usage:
    python extensions/dp_aggregate_reporting.py --n 2000 --epsilons 0.1,0.5,1.0,5.0
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


def privatize_report(rows, epsilon, seed=42):
    """
    Privatizes two aggregate breakdowns from a scored event set: governance
    action distribution, and department-level event counts. Returns both
    the true and noisy versions plus the utility cost (MAE) for
    transparency -- a real deployment would release ONLY the noisy
    version; both are shown here for this prototype's own evaluation.
    """
    rng = random.Random(seed)

    true_action_counts = dict(Counter(r["governance_action"] for r in rows))
    true_dept_counts = dict(Counter(r["department"] for r in rows))

    noisy_action_counts = privatize_counts(true_action_counts, epsilon, rng=rng)
    noisy_dept_counts = privatize_counts(true_dept_counts, epsilon, rng=rng)

    return {
        "epsilon": epsilon,
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
    ap.add_argument("--epsilons", type=str, default="0.1,0.5,1.0,5.0", help="Comma-separated epsilon values to evaluate.")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=str, default="experiments/output/dp_report.json")
    args = ap.parse_args()

    epsilons = [float(x) for x in args.epsilons.split(",")]

    rows = generate_events(args.n, "config/known_endpoints.yaml", seed=args.seed)
    score_events(rows)  # adds governance_action/governance_reason in place

    detail = privatize_report(rows, epsilon=epsilons[len(epsilons) // 2], seed=args.seed)
    sweep = run_epsilon_sweep(rows, epsilons, seed=args.seed)

    result = {
        "n_events": len(rows),
        "epsilon_sweep": sweep,
        "detail_at_median_epsilon": detail,
        "scope_note": (
            "Laplace mechanism applied to aggregate count/histogram queries "
            "over governance_action and department, computed from 100% "
            "synthetic Faker-generated events. No privacy budget composition "
            "tracking across multiple releases -- see this module's docstring "
            "for that and other stated limitations. Not federated learning, "
            "not DP-SGD training."
        ),
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Privacy/utility sweep across epsilon={epsilons} (lower epsilon = more privacy, more noise):")
    for row in sweep:
        print(f"  epsilon={row['epsilon']}: action_dist MAE={row['action_distribution_mae']}, "
              f"dept_dist MAE={row['department_distribution_mae']}")
    print(f"Report -> {args.out}")


if __name__ == "__main__":
    main()
