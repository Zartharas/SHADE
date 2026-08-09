#!/usr/bin/env python3
"""
tests/test_pipeline.py

Internal self-check suite for Project SHADE (16 checks as of ADR 0004).
Started as three focused checks for the two places in the original
pipeline with actual branching/security-relevant logic -- the governance
decision matrix (paper Section 4.4) and the DLP redaction patterns
(Section 5.2) -- and grew a regression-test block for each opt-in
extension as it graduated into shade/ (the policy proposer's
verify/guardrail behavior per ADR 0002, the MCP monitor's second
governance table per ADR 0003, and the DP reporter's Laplace mechanism
per ADR 0004). Still not a full test suite in the general sense -- it's
scoped to the places a silent regression would matter, not to exhaustive
coverage of every function -- but "two places" no longer describes what's
actually checked here; see docs/benchmark.md and the ADRs above for what
each block of tests actually verifies.

Usage:
    python3 tests/test_pipeline.py      # from repo root
    python3 -m tests.test_pipeline      # equivalent, module form
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
import shade.dp_aggregate_reporting as dp_reporting


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


def test_dlp_benchmark_confidence_intervals_are_well_formed():
    # Every reported point estimate must sit strictly inside its own
    # confidence interval (or the interval must be [None, None] when the
    # denominator was zero) -- a basic sanity check that wilson_ci() and
    # the report-assembly code in score() didn't get the bounds backwards
    # or drop a value.
    report = eval_harness.run(n=300, seed=42, out_path=None)
    all_metric_blocks = [report["micro_avg"]] + list(report["per_pattern"].values())
    for block in all_metric_blocks:
        for metric_name, ci_name in [("precision", "precision_ci_95"), ("recall", "recall_ci_95")]:
            point, ci = block[metric_name], block[ci_name]
            lower, upper = ci
            if point is None:
                assert lower is None and upper is None
            else:
                assert lower is not None and upper is not None
                assert lower <= point <= upper, f"{metric_name} point estimate {point} outside its own CI {ci}"
                assert 0.0 <= lower <= upper <= 1.0, f"{metric_name} CI {ci} outside the valid [0,1] range"


def test_dlp_bootstrap_f1_ci_degenerates_but_wilson_plugin_does_not():
    # Documents a real, easy-to-miss property of nonparametric bootstrap
    # confidence intervals rather than letting it surface silently: when
    # the observed sample has zero classification errors (the case this
    # benchmark's F1=1.0 usually lands in), EVERY bootstrap resample of
    # that sample is also error-free, so the bootstrap distribution has
    # zero variance and the resulting interval collapses to [1.0, 1.0] --
    # which looks like perfect certainty but is actually an artifact of
    # the method, not evidence of it. f1_ci_95_wilson_plugin exists
    # specifically to give a genuine, non-degenerate interval in exactly
    # this case (see f1_wilson_plugin_ci()'s docstring). This test fails
    # loudly if a future change accidentally "fixes" (i.e. hides) the
    # degenerate bootstrap behavior without anyone noticing, or if the
    # Wilson plug-in interval stops being wider than the degenerate one.
    report = eval_harness.run(n=300, seed=42, out_path=None)
    m = report["micro_avg"]
    assert m["f1"] == 1.0, "this test assumes the benchmark still scores a perfect F1 at n=300, seed=42"
    assert m["f1_ci_95"] == [1.0, 1.0], (
        "expected the nonparametric bootstrap to degenerate to [1.0, 1.0] "
        "on an error-free sample -- if this changed, re-check "
        "bootstrap_f1_ci()'s resampling logic."
    )
    plugin_lower, plugin_upper = m["f1_ci_95_wilson_plugin"]
    assert plugin_lower < 1.0, (
        f"expected the Wilson plug-in F1 interval's lower bound ({plugin_lower}) "
        f"to be strictly below 1.0 even at a perfect observed score -- that's "
        f"the entire reason this second interval exists."
    )
    assert plugin_upper == 1.0


def test_dlp_confidence_intervals_tighten_with_more_samples():
    # A basic, honest sanity check that the CIs actually respond to sample
    # size the way statistical theory says they must: more evidence should
    # never produce a WIDER interval for the same underlying (perfect)
    # result. Uses the same seed at two scales so the only thing that
    # differs is n.
    small = eval_harness.run(n=300, seed=42, out_path=None)
    large = eval_harness.run(n=3000, seed=42, out_path=None)
    small_lower = small["micro_avg"]["precision_ci_95"][0]
    large_lower = large["micro_avg"]["precision_ci_95"][0]
    assert large_lower > small_lower, (
        f"expected the n=3000 lower CI bound ({large_lower}) to be tighter "
        f"(higher, since both scored perfectly) than the n=300 bound "
        f"({small_lower}) -- more samples should narrow the interval."
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


def test_dp_laplace_mechanism_produces_valid_counts():
    # shade/dp_aggregate_reporting.py's privatize_counts() must always
    # return non-negative integer counts, regardless of noise direction --
    # see docs/adr/0004-integrating-dp-aggregate-reporting.md.
    import random
    true_counts = {"ALLOW": 100, "BLOCK": 3, "REDACT_THEN_ALLOW": 20}
    rng = random.Random(7)
    noisy = dp_reporting.privatize_counts(true_counts, epsilon=1.0, rng=rng)
    assert set(noisy.keys()) == set(true_counts.keys())
    for v in noisy.values():
        assert isinstance(v, int) and v >= 0, f"noisy count {v} is not a non-negative int"


def test_dp_mean_absolute_error_matches_hand_computation():
    true_counts = {"A": 10, "B": 20, "C": 30}
    noisy_counts = {"A": 12, "B": 18, "C": 30}
    # |10-12| + |20-18| + |30-30| = 2 + 2 + 0 = 4; MAE = 4 / 3
    expected = 4 / 3
    got = dp_reporting.mean_absolute_error(true_counts, noisy_counts)
    assert abs(got - expected) < 1e-9, f"MAE {got} != expected {expected}"


def test_dp_epsilon_sweep_mae_trends_downward():
    # Formalizes the privacy/utility trade-off docs/extensions.md describes
    # qualitatively: as epsilon increases (less noise), MAE should trend
    # downward on average across a fixed synthetic event set. Uses a fixed
    # seed and a large-ish n to keep this a reliable, non-flaky check of a
    # statistical trend, not a per-value guarantee.
    from shade.generate_synthetic_data import generate as generate_events
    from shade.governance_score import score_events
    rows = generate_events(500, "config/known_endpoints.yaml", seed=42)
    score_events(rows)
    sweep = dp_reporting.run_epsilon_sweep(rows, [0.1, 1.0, 10.0], seed=42)
    maes = [r["action_distribution_mae"] for r in sweep]
    assert maes[0] >= maes[-1], (
        f"expected MAE at epsilon=0.1 ({maes[0]}) to be >= MAE at epsilon=10.0 "
        f"({maes[-1]}) -- more privacy (lower epsilon) should mean more noise"
    )


def test_dp_pipeline_stage_privatizes_this_runs_own_events():
    # The load-bearing integration claim from ADR 0004: the pipeline stage
    # chains to the SAME already-scored events a run produced, not a
    # freshly regenerated population. Simulates what shade/run_pipeline.py
    # does: generate+score once, privatize that exact list, and confirm
    # the "true" counts in the DP report match that list's real action
    # distribution exactly (only the "dp_released" side has noise).
    from collections import Counter
    from shade.generate_synthetic_data import generate as generate_events
    from shade.governance_score import score_events
    rows = generate_events(200, "config/known_endpoints.yaml", seed=123)
    score_events(rows)
    expected_true = dict(Counter(r["governance_action"] for r in rows))
    report = dp_reporting.privatize_report(rows, epsilon=1.0, seed=123)
    assert report["action_distribution"]["true"] == expected_true


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
