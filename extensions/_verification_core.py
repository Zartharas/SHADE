#!/usr/bin/env python3
"""
extensions/_verification_core.py

Shared generalized formal-verification helper, factored out of
extensions/llm_policy_proposer.py so extensions/mcp_tool_call_monitor.py
can reuse the SAME verification logic for its own two-axis decision table
rather than duplicating it (duplicated verification logic would undercut
the "single auditable source of truth" reasoning in
docs/adr/0001-formal-verification-of-governance-matrix.md).

Same method as ADR 0001 and shade/verify_policy.py: exhaustive enumeration over
a finite two-axis domain. Still the right tool as long as the domain stays
a flat table with no combinators -- see that ADR for when to reconsider.
"""
import itertools


def verify_arbitrary_matrix(matrix, axis1_values, axis2_values, known_actions):
    """Returns a list of violation strings; empty = verified complete,
    well-formed, and non-conflicting over the given two-axis domain."""
    violations = []
    domain = set(itertools.product(axis1_values, axis2_values))
    matrix_keys = set(matrix.keys())

    for cell in domain:
        if cell not in matrix:
            violations.append(f"Domain cell {cell} has no explicit entry (would need a fallback).")
    for key in matrix_keys - domain:
        violations.append(f"Matrix key {key} is outside the declared domain {sorted(domain)}.")
    if len(matrix_keys) != len(matrix):
        violations.append("Matrix has duplicate keys (should be impossible for a dict).")
    for key, value in matrix.items():
        action = value[0] if isinstance(value, tuple) else value
        if action not in known_actions:
            violations.append(f"Entry {key} -> {action!r} is not in the known action vocabulary {sorted(known_actions)}.")

    return violations
