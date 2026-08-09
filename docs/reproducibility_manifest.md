# Reproducibility manifest

This document maps every quantitative result this repository currently
produces to the exact command, seed, and output file that generated it,
plus what environment provenance is auto-embedded in each report.

**What this is NOT:** a mapping from specific paper table/figure numbers
to commands. Doing that honestly would require cross-checking against
the actual submitted manuscript's final table/figure numbering, and this
document was built without access to that manuscript's content (`paper/`
is gitignored and its contents haven't been part of this work) --
inventing a "Table 3 -> this command" mapping without verifying it
against the real, submitted numbering would risk a false alignment,
which is exactly the kind of unverified claim this project has been
careful to avoid throughout (see `CONTRIBUTING.md` and every ADR's
citation discipline). **If you're the maintainer preparing a
camera-ready or a reviewer response**, use this document's stable IDs
(the left column below) to build that final mapping yourself once you
have the actual manuscript in front of you -- that's a five-minute task
with this table in hand, versus a risk of silently-wrong figure
references without it.

## Result-to-command mapping

| ID | Result | Command | Output file | Notes |
|---|---|---|---|---|
| `gov-matrix-verify` | Governance decision matrix: completeness + non-conflict (exhaustive enumeration) | `python3 shade/verify_policy.py` | stdout only (no file by default) | See `docs/adr/0001-formal-verification-of-governance-matrix.md`. Deterministic -- no seed. |
| `dlp-easy-tier` | DLP precision/recall/F1 + 95% CIs at n=300, seed=42 (the number CI runs on every push) | `python3 shade/eval_harness.py --n 300 --seed 42` | `experiments/output/dlp_benchmark_report.json` | Deterministic given `--seed`. Report includes `provenance` and `reproduction_command` fields (see below). |
| `dlp-scale-check` | DLP F1 at n=2,000 and n=10,000, seed=42 | `python3 shade/eval_harness.py --n 2000 --seed 42` / `--n 10000` | same as above, different `--out` per run | See `docs/benchmark.md`'s "Scale check" section for the recorded values. |
| `dlp-multi-seed` | DLP F1 across 7 seeds (42, 1, 7, 99, 12345, 2026, 555) | `for s in 1 7 99 12345 2026 555; do python3 shade/eval_harness.py --n 1000 --seed $s; done` | one file per seed if `--out` given per run | See `docs/benchmark.md`'s multi-seed sections (both the original 5-seed check and the extended 2-seed addition). |
| `dlp-hard-tier` | DLP recall on the diagnostic hard tier (OCR noise, homoglyphs, obfuscation, intl formats): 22.2% overall | `python3 shade/eval_harness.py --tier hard` | `experiments/output/dlp_hard_tier_report.json` | Fixed, hand-curated dataset -- no seed (deterministic by construction, not by RNG). See `docs/benchmark.md`'s "Harder benchmark tier" section. |
| `policy-proposer-regression` | Policy proposer: normal case passes verification, broken backend rejected, `DECISION_MATRIX` never mutated | `python3 tests/test_pipeline.py` (or `python3 shade/policy_proposer.py --context "..."` standalone) | stdout / `output/policy_proposal.json` if run via pipeline flag | See `docs/adr/0002-integrating-llm-policy-proposer.md`. |
| `mcp-monitor-stats` | MCP tool-call monitor: decision matrix verified, synthetic call distribution | `python3 shade/mcp_tool_call_monitor.py --n 500` | `output/mcp_tool_calls.csv` + `_summary.json` | Deterministic given `--seed` (default 42). See `docs/adr/0003-integrating-mcp-tool-call-monitor.md`. |
| `dp-privacy-utility` | DP aggregate reporting: MAE vs. epsilon sweep, the "absolute MAE flat, relative MAE improves 10x" finding | `python3 shade/dp_aggregate_reporting.py --n 500 --epsilons 0.1,0.5,1.0,5.0,10.0` (repeat at `--n 5000` for the scale comparison) | `output/dp_report.json` (standalone) or via `--out` | See `docs/benchmark.md`'s "Scale check" section and `docs/adr/0004-integrating-dp-aggregate-reporting.md`. |
| `extended-benchmark-full` | Full at-scale sweep: DLP at n=2,000/10,000, 6-seed check at n=1,000, all three extensions under load at n=5,000 | `python3 scripts/run_extended_benchmark.py` | `experiments/output/extended_benchmark_report.json` | Single command reproduces everything in `docs/benchmark.md`'s "Scale check" section at once. Also runnable via Docker or the manually-triggered `extended-benchmark` CI job -- see README's "Reproducing at scale". |
| `pipeline-e2e` | Full pipeline run (all five phases + optional extension stages) | `python3 shade/run_pipeline.py --n 2000 [--propose_policy_review] [--include_mcp_monitoring] [--privatize_governance_report]` | `output/*.csv`, `output/*.json`, `output/dashboard.png`, `output/VALIDATION_REPORT.md` | Deterministic given the default seed inside `shade/generate_synthetic_data.py`. This is the one set of outputs NOT provenance-stamped (see "What's provenance-stamped" below) since it's the core pipeline's stable, long-documented output contract. |

## What's provenance-stamped

`shade/eval_harness.py` (both tiers) and `scripts/run_extended_benchmark.py`
embed a `provenance` block and a `reproduction_command` string directly in
their JSON output, via `shade/provenance.py`:

```json
"provenance": {
  "git_commit_full": "...",
  "git_commit_short": "...",
  "git_dirty": false,
  "python_version": "3.11.x",
  "package_versions": {"faker": "...", "pandas": "...", "numpy": "...", "matplotlib": "...", "pyyaml": "..."},
  "generated_at_utc": "2026-08-09T19:38:07+00:00"
}
```

`git_dirty: true` means the report was generated from a working tree with
uncommitted changes -- still reproducible in spirit (the code that ran is
knowable from the diff at that moment) but not from the commit hash
alone. Every report in this repository's own `docs/benchmark.md` was
generated with `git_dirty: false` unless stated otherwise.

**Why not the core pipeline's output files too?** `output/synthetic_usage.csv`,
`output/governance_report.json`, and the rest of `shade/run_pipeline.py`'s
default outputs deliberately do NOT get a `provenance` field. Adding one
would mean every default pipeline run produces files with new content --
exactly the kind of silent output-contract growth ADR 0002 through 0004
each explicitly reasoned about and rejected for their own opt-in stages
(see e.g. ADR 0002's "Alternatives considered" on why the policy-review
stage stayed opt-in rather than default-on). The benchmark/diagnostic
reports don't carry that same stability expectation -- they're
regenerated and read individually, not treated as a fixed contract
downstream code depends on -- so provenance was added there without the
same tension.

## Reproducing everything in one pass

```bash
python3 shade/verify_policy.py
python3 shade/eval_harness.py --n 300 --seed 42
python3 shade/eval_harness.py --tier hard
python3 scripts/run_extended_benchmark.py
python3 tests/test_pipeline.py
```

Or, for full environment independence:

```bash
docker build -t shade .
docker run --rm -v "$(pwd)/experiments/output:/app/experiments/output" shade python3 scripts/run_extended_benchmark.py
docker run --rm shade python3 tests/test_pipeline.py
```
