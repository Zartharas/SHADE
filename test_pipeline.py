#!/usr/bin/env python3
"""
test_pipeline.py
Three focused internal checks for the two places in Project SHADE with
actual branching/security-relevant logic: the governance decision matrix
(paper Section 4.4) and the DLP redaction patterns (Section 5.2).
Not a full test suite -- just enough to fail loudly if either breaks.

Usage:
    python test_pipeline.py
"""
from governance_score import decide, decide_with_reason
from dlp_redact import redact_text
import verify_policy
import eval_harness


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
