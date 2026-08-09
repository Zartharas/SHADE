#!/usr/bin/env python3
"""
tests/test_pipeline.py
Three focused internal checks for the two places in Project SHADE with
actual branching/security-relevant logic: the governance decision matrix
(paper Section 4.4) and the DLP redaction patterns (Section 5.2).
Not a full test suite -- just enough to fail loudly if either breaks.

Usage:
    python tests/test_pipeline.py       # from repo root
    python -m tests.test_pipeline       # equivalent, module form
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shade.governance_score import decide, decide_with_reason
from shade.dlp_redact import redact_text
import shade.verify_policy as verify_policy
import shade.eval_harness as eval_harness
import shade.policy_proposer as policy_proposer
import shade.mcp_tool_call_monitor as mcp_monitor


def test_decision_matrix_covers_every_cell():
    # Every (tool_risk, data_sensitivity) combination in paper Section 4.4's
    # table must resolve to a real action, not the ALLOW_WITH_MONITORING fallback.
    expected = {
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
    for (tool_risk, sensitivity), want in expected.items():
        got = decide(tool_risk, sensitivity)
        assert got == want, f"decide({tool_risk!r}, {sensitivity!r}) = {got!r}, want {want!r}"


def test_dlp_redacts_each_pattern_type():
    text = (
        "here is a key sk-fake-AbCdEfGhIjKlMnOpQrStUvWx and my email is "
        "person@example.com, ssn 123-45-6789, call 555-123-4567"
    )
    redacted, hits = redact_text(text)
    assert "fake_api_key" in hits, "API-key-shaped string was not detected"
    assert "email" in hits, "Email was not detected"
    assert "ssn_shaped" in hits, "SSN-shaped string was not detected"
    assert "phone" in hits, "Phone number was not detected"
    assert "sk-fake-" not in redacted, "API key survived redaction"
    assert "person@example.com" not in redacted, "Email survived redaction"


def test_governance_matrix_formally_verified():
    # Independent formal check (see verify_policy.py and
    # docs/adr/0001-formal-verification-of-governance-matrix.md): every
    # cell of the 3x3 tool_risk x data_sensitivity domain must resolve to
    # an explicit, non-conflicting action, never the silent fallback. This
    # is deliberately not a restatement of the expected-value table above --
    # it re-derives the domain from first principles and checks the matrix
    # against it, rather than checking the matrix against itself.
    report = verify_policy.run_all_checks()
    assert report["completeness"] == "PASS"
    assert report["well_formedness"] == "PASS"
    assert report["no_silent_fallback"] == "PASS"
    assert report["matrix_entries"] == report["domain_size"] == 9


def test_decide_with_reason_matches_decide_and_has_reason():
    for (tool_risk, sensitivity) in verify_policy.full_domain():
        action = decide(tool_risk, sensitivity)
        action2, reason = decide_with_reason(tool_risk, sensitivity)
        assert action == action2, "decide() and decide_with_reason() disagree on action"
        assert isinstance(reason, str) and len(reason) > 0, "reason must be a non-empty string"


def test_dlp_evaluation_harness_meets_threshold():
    # Runs the expanded evaluation harness (eval_harness.py) against its
    # own structurally-varied synthetic benchmark set (300 samples, fixed
    # seed=42 for reproducibility) and asserts a minimum micro-averaged F1.
    # This is internal consistency against synthetic ground truth, not a
    # real-world accuracy claim -- see docs/benchmark.md and
    # eval_harness.py's own docstring for the full scope statement.
    report = eval_harness.run(n=300, seed=42, out_path=None)
    f1 = report["micro_avg"]["f1"]
    assert f1 is not None and f1 >= 0.95, (
        f"DLP benchmark micro-F1 {f1} fell below the 0.95 threshold "
        f"(see experiments/output/dlp_benchmark_report.json for detail "
        f"after running eval_harness.py directly)."
    )
    for pattern, metrics in report["per_pattern"].items():
        assert metrics["f1"] is not None and metrics["f1"] >= 0.90, (
            f"{pattern} F1 {metrics['f1']} fell below 0.90 threshold."
        )


def test_policy_proposer_default_domain_passes_verification():
    # shade/policy_proposer.py's HeuristicMockBackend, run over the existing
    # (unchanged) 3x3 domain, must produce a proposal that passes formal
    # verification -- this is the "normal, nothing weird" case that should
    # never fail. See docs/adr/0002-integrating-llm-policy-proposer.md.
    result = policy_proposer.propose_and_verify("regression test: default domain", out_path=None)
    assert result["status"] == "CANDIDATE_PENDING_HUMAN_REVIEW"
    assert result["formal_verification"]["status"] == "PASS"
    assert result["formal_verification"]["violations"] == []


def test_policy_proposer_rejects_a_broken_backend():
    # Formalizes the guardrail check that was previously only run ad hoc:
    # a backend that omits a cell and uses an invalid action label must be
    # REJECTED, not silently written out as a candidate. This is the load-
    # bearing claim for this module -- that formal verification actually
    # catches bad proposals, not just well-formed ones.
    class BrokenBackend(policy_proposer.PolicyProposerBackend):
        def propose(self, current_matrix, current_reasons, context, axis1_values, axis2_values):
            proposed = dict(current_matrix)
            proposed.pop(("low", "public"), None)  # incompleteness
            proposed[("high", "critical")] = "MAYBE_BLOCK_IDK"  # invalid action
            return proposed, dict(current_reasons), "deliberately broken test proposal"

    result = policy_proposer.propose_and_verify(
        "regression test: broken backend", backend=BrokenBackend(), out_path=None
    )
    assert result["status"] == "REJECTED_FAILED_VERIFICATION"
    assert len(result["formal_verification"]["violations"]) == 2


def test_policy_proposer_never_mutates_decision_matrix():
    # The non-negotiable safety property from ADR 0002: no proposal, valid
    # or broken, is ever applied to the real DECISION_MATRIX. Snapshot it,
    # run both the normal and broken-backend cases, and confirm it's
    # byte-for-byte identical afterward.
    from shade.governance_score import DECISION_MATRIX
    before = dict(DECISION_MATRIX)
    policy_proposer.propose_and_verify("mutation check: normal", out_path=None)
    test_policy_proposer_rejects_a_broken_backend()
    assert DECISION_MATRIX == before, "DECISION_MATRIX was mutated by a proposal -- this must never happen"


def test_mcp_decision_matrix_formally_verified():
    # shade/mcp_tool_call_monitor.py's MCP_DECISION_MATRIX is a second,
    # independently-authored (method_risk_class x data_sensitivity)
    # governance table -- see docs/adr/0003-integrating-mcp-tool-call-monitor.md.
    # Confirms the generalized verifier from ADR 0002 correctly accepts
    # this hand-authored-but-well-formed table, not just the original one.
    violations = verify_policy.verify_arbitrary_matrix(
        mcp_monitor.MCP_DECISION_MATRIX,
        mcp_monitor.METHOD_RISK_CLASSES,
        mcp_monitor.DATA_SENSITIVITY_LEVELS,
        mcp_monitor.KNOWN_ACTIONS,
    )
    assert violations == [], f"MCP_DECISION_MATRIX failed formal verification: {violations}"


def test_mcp_verifier_rejects_a_broken_matrix():
    # Mirrors test_policy_proposer_rejects_a_broken_backend's load-bearing
    # claim, applied to the second governance table: an incomplete matrix
    # using an invalid action label must be flagged, not silently accepted.
    broken = dict(mcp_monitor.MCP_DECISION_MATRIX)
    broken.pop(("read", "public"), None)  # incompleteness
    broken[("execute", "critical")] = "MAYBE_BLOCK_IDK"  # invalid action
    violations = verify_policy.verify_arbitrary_matrix(
        broken,
        mcp_monitor.METHOD_RISK_CLASSES,
        mcp_monitor.DATA_SENSITIVITY_LEVELS,
        mcp_monitor.KNOWN_ACTIONS,
    )
    assert len(violations) == 2, f"expected 2 violations (1 missing cell, 1 invalid action), got: {violations}"


def test_mcp_synthetic_tool_calls_are_well_formed():
    # Generator smoke test: fixed seed for reproducibility, every row has
    # the documented fields, every governance_action was actually produced
    # by decide_tool_call() (not some other value), and dlp_hits is valid
    # JSON (redact_text's contract, reused from shade/dlp_redact.py).
    rows = mcp_monitor.generate_synthetic_tool_calls(50, seed=42)
    assert len(rows) == 50
    expected_fields = {
        "call_id", "timestamp", "mcp_server", "method", "method_risk_class",
        "data_sensitivity", "args_summary_redacted", "dlp_hits", "governance_action",
    }
    for row in rows:
        assert set(row.keys()) == expected_fields
        assert row["governance_action"] == mcp_monitor.decide_tool_call(
            row["method_risk_class"], row["data_sensitivity"]
        )
        json.loads(row["dlp_hits"])  # must be valid JSON, raises if not

    report = mcp_monitor.summarize(rows)
    assert report["total_calls"] == 50
    assert sum(report["by_governance_action"].values()) == 50


def test_dlp_leaves_clean_text_untouched():
    clean = "This paragraph has no sensitive patterns in it at all."
    redacted, hits = redact_text(clean)
    assert hits == {}, f"False positive on clean text: {hits}"
    assert redacted == clean


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS: {t.__name__}")
    print(f"\n{len(tests)}/{len(tests)} checks passed.")
