#!/usr/bin/env python3
"""
scripts/run_extended_benchmark.py

Optional, opt-in extended benchmark -- NOT part of tests/test_pipeline.py
and NOT run on every CI push. Reproduces the higher-volume, multi-seed
numbers documented in docs/benchmark.md's "Scale check" section without
hand-typing a dozen commands. Runnable directly, inside Docker (see
Dockerfile), or via the "extended-benchmark" GitHub Actions job (manually
triggered -- see .github/workflows/test.yml).

WHY THIS IS SEPARATE FROM tests/test_pipeline.py:
- tests/test_pipeline.py is the fast (~seconds), always-on correctness
  gate: n=300 DLP benchmark, formal verification, guardrail regression
  tests. It runs on every push and must stay fast, so it deliberately
  does not test at the volumes this script does.
- This script is slower (n up to 10,000, 7 total seeds across two checks,
  3 extension stress runs plus a combined run at n=5,000) and answers a
  different question: does correctness hold AT SCALE, not just at the
  small n CI uses for speed. A failure here does not mean the same thing
  a tests/test_pipeline.py failure does -- it means a scale-dependent
  issue was found that the fast suite structurally cannot catch. Neither
  script replaces the other.

100% synthetic Faker-generated data throughout, consistent with the rest
of this repository (paper Data availability statement). No network calls.

Usage:
    python3 scripts/run_extended_benchmark.py
    python3 scripts/run_extended_benchmark.py --out experiments/output/extended_benchmark_report.json

Inside Docker:
    docker run --rm shade python3 scripts/run_extended_benchmark.py
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import shade.eval_harness as eval_harness

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (n, seed) pairs for the scale check -- same seed (42, the repo-wide
# default), increasing volume.
DLP_SCALE_CASES = [(300, 42), (2000, 42), (10000, 42)]

# (n, seed) pairs for the multi-seed check -- fixed n, varying seed.
DLP_MULTI_SEED_CASES = [(1000, s) for s in (1, 7, 99, 12345, 2026, 555)]

# Each opt-in pipeline extension (ADR 0002-0004) stress-tested at n=5000
# (25x the n=100-200 used during their original integration verification),
# individually and all together. expected_extra_files lets this script
# confirm the flag actually produced its documented output, not just that
# the process exited 0.
EXTENSION_RUNS = [
    {
        "name": "propose_policy_review",
        "flags": ["--propose_policy_review"],
        "n": 5000,
        "expected_extra_files": {"policy_proposal.json"},
    },
    {
        "name": "include_mcp_monitoring",
        "flags": ["--include_mcp_monitoring"],
        "n": 5000,
        "expected_extra_files": {"mcp_tool_calls.csv", "mcp_tool_calls_summary.json"},
    },
    {
        "name": "privatize_governance_report",
        "flags": ["--privatize_governance_report"],
        "n": 5000,
        "expected_extra_files": {"dp_report.json"},
    },
    {
        "name": "all_three_together",
        "flags": ["--propose_policy_review", "--include_mcp_monitoring", "--privatize_governance_report"],
        "n": 5000,
        "expected_extra_files": {
            "policy_proposal.json", "mcp_tool_calls.csv",
            "mcp_tool_calls_summary.json", "dp_report.json",
        },
    },
]


def run_dlp_case(n, seed):
    report = eval_harness.run(n=n, seed=seed, out_path=None)
    return {
        "n": n, "seed": seed,
        "precision": report["micro_avg"]["precision"],
        "recall": report["micro_avg"]["recall"],
        "f1": report["micro_avg"]["f1"],
    }


def run_extension_case(case):
    output_dir = os.path.join(REPO_ROOT, "output")
    shutil.rmtree(output_dir, ignore_errors=True)  # clean slate per case

    start = time.time()
    result = subprocess.run(
        [sys.executable, "shade/run_pipeline.py", "--n", str(case["n"])] + case["flags"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    elapsed = round(time.time() - start, 2)

    process_ok = result.returncode == 0
    output_files = set(os.listdir(output_dir)) if process_ok and os.path.isdir(output_dir) else set()
    files_ok = case["expected_extra_files"].issubset(output_files)
    ok = process_ok and files_ok

    return {
        "name": case["name"], "n": case["n"], "flags": case["flags"],
        "elapsed_sec": elapsed, "exit_code": result.returncode,
        "process_ok": process_ok, "expected_files_present": files_ok, "ok": ok,
        "output_files": sorted(output_files),
        "stderr_tail": result.stderr[-500:] if not ok else "",
    }


def run_pipeline_test_suite():
    start = time.time()
    result = subprocess.run(
        [sys.executable, "tests/test_pipeline.py"], cwd=REPO_ROOT,
        capture_output=True, text=True,
    )
    elapsed = round(time.time() - start, 2)
    return {"ok": result.returncode == 0, "elapsed_sec": elapsed}


def main():
    ap = argparse.ArgumentParser(
        description="Extended (opt-in, slower) benchmark: DLP at scale, multi-seed, extensions under load."
    )
    ap.add_argument("--out", type=str, default="experiments/output/extended_benchmark_report.json")
    args = ap.parse_args()

    print("=== Extended benchmark (opt-in; not part of the fast CI gate -- see tests/test_pipeline.py) ===\n")

    print("[1/4] DLP benchmark at increasing scale (seed=42)...")
    scale_results = [run_dlp_case(n, s) for n, s in DLP_SCALE_CASES]
    for r in scale_results:
        print(f"  n={r['n']:>6} seed={r['seed']}: precision={r['precision']} recall={r['recall']} f1={r['f1']}")

    print("\n[2/4] DLP benchmark across multiple seeds (n=1000 each)...")
    seed_results = [run_dlp_case(n, s) for n, s in DLP_MULTI_SEED_CASES]
    for r in seed_results:
        print(f"  seed={r['seed']:>6} n={r['n']}: precision={r['precision']} recall={r['recall']} f1={r['f1']}")

    print("\n[3/4] Opt-in pipeline extensions under load (n=5000 each)...")
    extension_results = [run_extension_case(c) for c in EXTENSION_RUNS]
    for r in extension_results:
        status = "OK" if r["ok"] else "FAILED"
        print(f"  {r['name']:<32} n={r['n']} flags={r['flags']}: {status} in {r['elapsed_sec']}s")
        if not r["ok"]:
            print(f"    process_ok={r['process_ok']} expected_files_present={r['expected_files_present']}")
            if r["stderr_tail"]:
                print(f"    stderr: {r['stderr_tail']}")

    print("\n[4/4] Re-running the fast correctness suite once more after all of the above...")
    suite_result = run_pipeline_test_suite()
    print(f"  tests/test_pipeline.py: {'PASS' if suite_result['ok'] else 'FAIL'} in {suite_result['elapsed_sec']}s")

    all_dlp_perfect = all(r["f1"] == 1.0 for r in scale_results + seed_results)
    all_extensions_ok = all(r["ok"] for r in extension_results)
    overall_ok = all_dlp_perfect and all_extensions_ok and suite_result["ok"]

    report = {
        "dlp_scale_check": scale_results,
        "dlp_multi_seed_check": seed_results,
        "extension_load_check": extension_results,
        "post_run_test_suite": suite_result,
        "overall_ok": overall_ok,
        "scope_note": (
            "All checks run against 100% synthetic Faker-generated data. A "
            "perfect DLP F1 here demonstrates the benchmark's own internal "
            "consistency at scale, not real-world detection accuracy -- see "
            "docs/benchmark.md for the full scope statement. This script is "
            "diagnostic/reproducibility tooling, not part of the pass/fail "
            "gate CI enforces on every push (that remains "
            "tests/test_pipeline.py)."
        ),
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n{'=' * 60}")
    print(f"Overall: {'PASS' if overall_ok else 'FAIL'} -> {args.out}")
    if not overall_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
