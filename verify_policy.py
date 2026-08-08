#!/usr/bin/env python3
"""
verify_policy.py
Formal verification of the governance decision matrix (paper Section 4.4),
see docs/adr/0001-formal-verification-of-governance-matrix.md for the
rationale behind the method chosen here.

Method: exhaustive enumeration over the finite (tool_risk x data_sensitivity)
domain. For a 3x3 = 9-cell domain this is a sound and complete decision
procedure -- explicit-state model checking, not an approximation of one --
so no SAT/SMT solver is used or needed. See the ADR for the trigger
conditions under which that choice should be revisited.

Two properties are checked:
  1. Completeness: every domain combination resolves to an explicitly
     authored action in DECISION_MATRIX, never through decide()'s silent
     ALLOW_WITH_MONITORING fallback.
  2. Non-conflict / well-formedness: DECISION_MATRIX has exactly one entry
     per domain combination (no duplicates, no missing, no stray keys
     outside the declared domain), and every action is drawn from the
     fixed, known action vocabulary.

Usage:
    python verify_policy.py
Exits 0 and prints a report on success; raises AssertionError (nonzero
exit) with a specific violation on failure.
"""
from itertools import product

from governance_score import DECISION_MATRIX, DECISION_REASONS, decide

TOOL_RISK_LEVELS = ("high", "medium", "low")
DATA_SENSITIVITY_LEVELS = ("critical", "sensitive", "public")

# The fixed action vocabulary the paper's Section 4.4 table is allowed to
# reference. Any action appearing in DECISION_MATRIX outside this set is a
# well-formedness violation (e.g. a typo introduced during editing).
KNOWN_ACTIONS = {
    "BLOCK",
    "BLOCK_WITH_OVERRIDE",
    "ALLOW",
    "REDACT_THEN_ALLOW",
    "ALLOW_WITH_MONITORING",
}

# The fallback decide() returns for any key absent from DECISION_MATRIX.
# Completeness means this value is never *needed* by the enumerated domain,
# even though it happens to also be a legitimate action for other cells.
FALLBACK_ACTION = "ALLOW_WITH_MONITORING"


def full_domain():
    """All 9 (tool_risk, data_sensitivity) combinations, enumerated."""
    return list(product(TOOL_RISK_LEVELS, DATA_SENSITIVITY_LEVELS))


def verify_completeness():
    """
    Every cell in the enumerated domain must have an EXPLICIT entry in
    DECISION_MATRIX (not merely a defined decide() return value, which
    could be silently satisfied by the fallback).
    Returns a list of violation strings; empty list = verified complete.
    """
    violations = []
    for cell in full_domain():
        if cell not in DECISION_MATRIX:
            violations.append(
                f"Domain cell {cell} has no explicit matrix entry; "
                f"decide() would silently return the fallback "
                f"{FALLBACK_ACTION!r} for it."
            )
    return violations


def verify_well_formed():
    """
    DECISION_MATRIX must contain exactly the 9 domain keys (no stray keys
    outside the declared tool_risk/data_sensitivity vocabulary, no
    duplicates -- impossible in a dict, but checked structurally here so
    the guarantee is asserted by this module rather than assumed from
    Python's dict semantics) and every value must be a known action.
    Returns a list of violation strings; empty list = verified well-formed.
    """
    violations = []
    domain = set(full_domain())
    matrix_keys = set(DECISION_MATRIX.keys())

    stray = matrix_keys - domain
    for key in stray:
        violations.append(f"Matrix key {key} is outside the declared domain.")

    if len(matrix_keys) != len(DECISION_MATRIX):
        violations.append("DECISION_MATRIX has duplicate keys (should be impossible for a dict).")

    for key, action in DECISION_MATRIX.items():
        if action not in KNOWN_ACTIONS:
            violations.append(
                f"Matrix entry {key} -> {action!r} is not in the known "
                f"action vocabulary {sorted(KNOWN_ACTIONS)}."
            )

    if len(matrix_keys) != 9:
        violations.append(f"DECISION_MATRIX has {len(matrix_keys)} entries; expected exactly 9.")

    # decide_with_reason() assumes every DECISION_MATRIX key also has a
    # DECISION_REASONS entry (governance_score.py indexes DECISION_REASONS
    # with a key already confirmed present in DECISION_MATRIX, uncaught if
    # that assumption is wrong). Check the two tables stay in lockstep so an
    # edit to one that forgets the other fails verification instead of
    # raising a KeyError at runtime.
    reason_keys = set(DECISION_REASONS.keys())
    missing_reasons = matrix_keys - reason_keys
    for key in missing_reasons:
        violations.append(f"Matrix key {key} has no matching DECISION_REASONS entry.")
    stray_reasons = reason_keys - domain
    for key in stray_reasons:
        violations.append(f"DECISION_REASONS key {key} is outside the declared domain.")

    return violations


def verify_no_silent_fallback_reachable():
    """
    Operational cross-check: actually call decide() for every domain cell
    and confirm the result matches the matrix's explicit entry, i.e. the
    fallback branch inside decide() is never the source of the returned
    action for any in-domain input. This is deliberately redundant with
    verify_completeness() -- one checks the data (the matrix), the other
    checks the code path (decide()) -- because the property we care about
    is "the running system never silently falls back," not just "the
    table looks complete on paper."
    Returns a list of violation strings; empty list = verified.
    """
    violations = []
    for cell in full_domain():
        tool_risk, data_sensitivity = cell
        expected = DECISION_MATRIX.get(cell)
        actual = decide(tool_risk, data_sensitivity)
        if expected is None:
            violations.append(
                f"{cell}: no explicit matrix entry, decide() returned "
                f"{actual!r} via fallback."
            )
        elif actual != expected:
            violations.append(
                f"{cell}: decide() returned {actual!r} but matrix says {expected!r}."
            )
    return violations


def run_all_checks(verbose=False):
    """
    Runs all three checks and raises AssertionError with every violation
    found (not just the first) if any check fails. Returns a small report
    dict on success.
    """
    all_violations = []
    all_violations += verify_completeness()
    all_violations += verify_well_formed()
    all_violations += verify_no_silent_fallback_reachable()

    if all_violations:
        detail = "\n  - ".join(all_violations)
        raise AssertionError(
            f"Governance decision matrix failed formal verification "
            f"({len(all_violations)} violation(s)):\n  - {detail}"
        )

    report = {
        "domain_size": len(full_domain()),
        "matrix_entries": len(DECISION_MATRIX),
        "completeness": "PASS",
        "well_formedness": "PASS",
        "no_silent_fallback": "PASS",
        "method": "exhaustive enumeration over finite domain (explicit-state model checking)",
    }
    if verbose:
        print("Formal verification of governance decision matrix: ALL CHECKS PASSED")
        for k, v in report.items():
            print(f"  {k}: {v}")
    return report


if __name__ == "__main__":
    run_all_checks(verbose=True)
