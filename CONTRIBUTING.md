# Contributing to Project SHADE

SHADE is a research prototype accompanying a submitted academic paper.
This file exists mainly so contributions (including future changes by the
maintainer) stay consistent with the project's constraints, not to recruit
outside contributors at scale.

## Ground rules

- **Synthetic data only.** Every input to this pipeline must originate
  from `generate_synthetic_data.py` (Faker-based) or from a benchmark
  generator like `eval_harness.py`'s own dataset builder. Do not add code
  paths that read, request, or simulate real organizational, employee, or
  customer data at any stage -- this is a hard constraint tied to the
  paper's Data availability and Ethics statements, not just a style
  preference.
- **No network calls.** The pipeline runs entirely offline. Keep it that
  way; if a future contribution needs network access (e.g. a real
  discovery integration), it belongs in the "Production tooling" table in
  the README as an external reference, not merged into this prototype.
- **Anonymity during review.** While the accompanying paper is under
  double-anonymous review, do not add anything that could attach a real
  identity to this repository: no restoring the redacted author field in
  `CITATION.cff`, no identifying names/emails in commit metadata, no links
  to identity-bearing profiles or the `paper/`/`academic_documentation/`
  directories (both gitignored on purpose -- see `.gitignore`). If you're
  unsure whether something is identity-bearing, leave it out and ask.
- **One implementation, shared by CLI and orchestrator.** Each phase's
  logic (discovery, DLP, governance, dashboard) should exist once, as
  functions called by both that phase's own `--help`-able CLI and
  `run_pipeline.py`. Don't fork the logic to add a feature to only one
  entry point.

## Before opening a change

1. Run the self-check: `python3 test_pipeline.py`. All checks must pass,
   including the formal verification (`verify_policy.py`) and DLP
   evaluation harness (`eval_harness.py`) thresholds.
2. Run the full pipeline smoke test: `python3 run_pipeline.py --n 500`.
3. If Docker is available locally, `docker build -t shade .` and
   `docker run --rm shade python3 test_pipeline.py` for an environment-
   independent check (see `Dockerfile`).
4. If the change touches a security- or governance-relevant decision (the
   decision matrix, DLP patterns, or anything with a "this could silently
   do the wrong thing" failure mode), write a short ADR in `docs/adr/`
   following the format in `docs/adr/0001-formal-verification-of-governance-matrix.md`:
   context, decision, alternatives considered, consequences. Code changes
   without the reasoning behind them are much harder to trust or revisit.

## Extending the decision matrix

If you add a new `tool_risk` or `data_sensitivity` level (growing the
matrix beyond 3x3), re-read
`docs/adr/0001-formal-verification-of-governance-matrix.md`'s
"Consequences" section first: exhaustive enumeration stops being the
obviously-right verification method once the domain grows or gains
combinators, and that ADR says explicitly what to reconsider (a SAT/SMT
encoding) if that happens.

## Extending the evaluation harness

New benchmark cases in `eval_harness.py` should include both true
positives (with structural variation, not copies of existing ones) and
near-miss distractors that could plausibly false-positive a different
pattern. Keep `docs/benchmark.md` in sync with any change to what is or
isn't measured -- the point of that document is to prevent the harness
from silently implying more than it proves as it grows.

## Style

Standard library first; the project is intentionally "zero-budget" in
its dependency footprint (see `requirements.txt`). If a new dependency
seems necessary, say why exhaustive/standard-library approaches aren't
sufficient, the same way `docs/adr/0001-...md` does for the verification
method.
