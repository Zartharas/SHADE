# ADR 0002: Integrating the LLM policy proposer into the core package

## Status

Accepted — 2026-08-08

## Context

`extensions/llm_policy_proposer.py` shipped as a standalone scaffold (see
`docs/extensions.md`): a `PolicyProposerBackend` interface with one
implementation (`HeuristicMockBackend`, deterministic, no live LLM call),
gated by a generalized formal-verification check before any proposal is
written out for human review. It was deliberately kept out of `shade/`
and uncovered by `tests/test_pipeline.py` because, at the time, it hadn't
been shown to meet the bar the rest of the core package holds itself to:
tested, documented in the module-relationship table, and consistent with
the pipeline's stable output contract.

The maintainer has since asked to integrate this one first (of the three
extensions), specifically because it carries the lowest overclaiming risk:
no live LLM call means there's no claim about real proposal quality to
overclaim, and the guardrail (formal verification rejecting a malformed
proposal) was already demonstrated working against a deliberately broken
backend, not just asserted.

Two things needed resolving before "integrate" could mean more than
"move the file":

1. `extensions/_verification_core.py`'s `verify_arbitrary_matrix()` was
   shared between this module and `extensions/mcp_tool_call_monitor.py`
   (still a standalone extension). If the proposer moves into `shade/`
   but keeps importing from `extensions/`, that's a core module depending
   on optional-extension code -- backwards layering that would make
   `shade/` no longer buildable/importable without `extensions/` present.
2. The original CLI only accepted a free-text `--context` string, with no
   connection to an actual pipeline run. "Integrated into the pipeline"
   should mean the proposer can act on a real run's own data, not just be
   invokable from the same repo.

## Decision

1. **Relocate `verify_arbitrary_matrix()` into `shade/verify_policy.py`**
   as the canonical, single-source generalized verifier, alongside the
   existing 3x3-specific `run_all_checks()`. This is a natural fit: ADR
   0001 already documents exhaustive enumeration as the chosen method and
   explicitly anticipated generalizing it. `extensions/mcp_tool_call_monitor.py`
   (which stays a standalone extension for now) imports it from
   `shade.verify_policy` going forward; `extensions/_verification_core.py`
   is removed rather than kept as a duplicate or a shim, since a shim with
   no remaining independent purpose is just a second place the same logic
   could drift.
2. **Move the module to `shade/policy_proposer.py`.** It keeps its
   `PolicyProposerBackend` interface and `HeuristicMockBackend` exactly as
   built -- no live LLM call is added by this integration, and that stays
   true until a real backend is separately implemented and evaluated
   (still explicitly future work, not attempted here or implied by this
   ADR).
3. **Add one new, opt-in pipeline stage**, not a default-on one:
   `shade/run_pipeline.py --propose_policy_review` runs the proposer after
   governance scoring, using the run's own `governance_report`
   (action distribution) as the `context` string, over the EXISTING
   3x3 domain (no new axis values by default -- extending the domain via
   `--add_tool_risk`/`--add_data_sensitivity` remains a `policy_proposer.py`
   CLI-only capability, not exposed through the pipeline flag). Output
   goes to `output/policy_proposal.json`, alongside the other reports,
   only when the flag is passed.
4. **The safety property is unchanged and non-negotiable**: no proposal is
   ever applied to `governance_score.DECISION_MATRIX`, with or without the
   new pipeline flag. Integration means "runs as part of the pipeline
   and is tested," not "can modify what the pipeline does." The pipeline
   flag increases visibility/convenience, not authority.
5. **Default pipeline behavior and output contract are unchanged.** Not
   passing `--propose_policy_review` produces byte-for-byte the same
   files it did before this ADR (verified below) -- this integration adds
   a capability, it does not alter what `docs/benchmark.md`'s and the
   README's existing claims about pipeline output describe.

## Alternatives considered

- **Leave it in `extensions/`, just add tests.** Would satisfy "tested"
  but not "integrated" in the sense the maintainer asked for (part of the
  actual pipeline run, not just covered by CI). Rejected as not actually
  doing what was asked.
- **Make the pipeline stage default-on.** Rejected: it would change the
  default output contract (a new file appears on every run) that
  `docs/benchmark.md` and the README currently describe precisely: for a
  project whose whole rigor argument rests on "internal consistency
  against your own synthetic ground truth, stated exactly," silently
  growing what a default run produces is exactly the kind of scope creep
  this project has otherwise been careful to avoid. Opt-in preserves the
  existing contract and adds a new, separately-documented one.
- **Let the pipeline flag also accept new axis values (extend the
  domain).** Rejected for this integration: exposing domain extension
  through the pipeline (rather than `policy_proposer.py`'s own CLI) would
  make an already-opt-in feature capable of proposing structurally new
  policy shapes as part of an ordinary pipeline run, raising the stakes of
  what "opt-in" means. Keeping domain extension a `policy_proposer.py`-only
  capability is a narrower, easier-to-reason-about boundary.

## Consequences

- `shade/verify_policy.py` now has two verification entry points: the
  concrete `run_all_checks()` for `governance_score.DECISION_MATRIX`, and
  the generic `verify_arbitrary_matrix()` any two-axis table can use.
  Anything needing the generic form (currently: `shade/policy_proposer.py`
  and `extensions/mcp_tool_call_monitor.py`) imports it from here.
- `extensions/_verification_core.py` is deleted; `docs/extensions.md` is
  updated to reflect that the LLM policy proposer is no longer one of the
  "three standalone extensions" (now two: MCP monitoring, DP reporting).
- `tests/test_pipeline.py` gains coverage for `shade/policy_proposer.py`:
  the default-domain proposal passes verification, and (formalizing what
  was previously an ad hoc manual check) a deliberately broken backend is
  correctly rejected.
- The README's module-relationship table and Layout section gain an entry
  for `shade/policy_proposer.py`.
- If MCP monitoring or DP reporting are integrated next (per the
  maintainer's stated one-at-a-time plan), each gets its own ADR following
  this one's numbering and the same "what changes, what stays opt-in,
  what's still not claimed" structure -- this ADR is a template for those,
  not a one-off.
