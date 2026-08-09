# Contributing to Project SHADE

SHADE is a research prototype accompanying a submitted academic paper.
This file exists mainly so contributions (including future changes by the
maintainer) stay consistent with the project's constraints, not to recruit
outside contributors at scale.

## Ground rules

- **Synthetic data only.** Every input to this pipeline must originate
  from `shade/generate_synthetic_data.py` (Faker-based) or from a benchmark
  generator like `shade/eval_harness.py`'s own dataset builder. Do not add code
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
  `shade/run_pipeline.py`. Don't fork the logic to add a feature to only one
  entry point.

## Before opening a change

1. Run the self-check: `python3 tests/test_pipeline.py`. All checks must pass,
   including the formal verification (`shade/verify_policy.py`) and DLP
   evaluation harness (`shade/eval_harness.py`) thresholds.
2. Run the full pipeline smoke test: `python3 shade/run_pipeline.py --n 500`.
3. If Docker is available locally, `docker build -t shade .` and
   `docker run --rm shade python3 tests/test_pipeline.py` for an environment-
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

New benchmark cases in `shade/eval_harness.py` should include both true
positives (with structural variation, not copies of existing ones) and
near-miss distractors that could plausibly false-positive a different
pattern. Keep `docs/benchmark.md` in sync with any change to what is or
isn't measured -- the point of that document is to prevent the harness
from silently implying more than it proves as it grows.

## Working in extensions/

`extensions/` holds optional, standalone prototypes -- not part of the
core pipeline, not covered by `tests/test_pipeline.py`, and each explicitly
scoped in `docs/extensions.md` (what it demonstrates and what it doesn't).
As of ADR 0004, the three originally-scoped extensions (LLM policy
proposer, MCP tool-call monitor, DP aggregate reporting) have all
graduated into `shade/`, so `extensions/` is currently empty -- this
section describes the standard for any NEW standalone prototype added
here in the future. If you add one:

- Keep it standalone. Don't add imports from `extensions/` into
  `shade/run_pipeline.py`, `tests/test_pipeline.py`, or any core-pipeline module --
  that would silently change what the documented, tested pipeline does.
- Reuse core logic where it genuinely fits (as the graduated modules do:
  `shade/dlp_redact.py`'s patterns, the exhaustive-enumeration verification
  method from ADR 0001, `shade/generate_synthetic_data.py`'s generator) instead
  of reimplementing it.
- Update `docs/extensions.md`'s scope/status section for whatever you
  changed -- the point of that document is to prevent a scaffold from
  silently implying more than it's actually been shown to do.
- Run it standalone (`python3 extensions/<file>.py`) before committing;
  see the "Smoke-test experiments/ scaffolding" step in
  `.github/workflows/test.yml` for the pattern CI uses to check a
  standalone script (that it runs without error, not a correctness
  assertion -- these are prototypes, not production code) and add an
  equivalent step for your new addition.

## Graduating an extension into shade/

Extensions move from `extensions/` into `shade/` one at a time, each with
its own ADR (see `docs/adr/0002-integrating-llm-policy-proposer.md` for the
first one and the template it sets; `docs/adr/0003-integrating-mcp-tool-call-monitor.md`
for a case where the integration shape had to differ -- a parallel
pipeline phase instead of a chained one -- because the module's data had
no real relationship to existing pipeline output; and
`docs/adr/0004-integrating-dp-aggregate-reporting.md` for a case where
"chained" itself had two possible meanings -- reusing this run's own
already-computed data vs. regenerating a fresh sample to process -- and
the ADR had to pick and justify one). A graduation ADR should cover: what
moves and why, what safety property must be preserved (e.g. "never
auto-applies to DECISION_MATRIX" for the policy proposer), whether it
becomes a default-on or opt-in pipeline stage (opt-in unless there's a
specific reason the default output contract should change -- see ADR 0002
for why that's the default answer), and what the module still does NOT
demonstrate even once integrated. Update `docs/extensions.md` to reflect
what moved and add regression tests to `tests/test_pipeline.py` for the
module's core claims, not just that it runs without crashing.

## Style

Standard library first; the project is intentionally "zero-budget" in
its dependency footprint (see `requirements.txt`). If a new dependency
seems necessary, say why exhaustive/standard-library approaches aren't
sufficient, the same way `docs/adr/0001-...md` does for the verification
method.
