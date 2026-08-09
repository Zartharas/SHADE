# ADR 0004: Integrating DP aggregate reporting into core pipeline

## Status

Accepted — 2026-08-09

## Context

`extensions/dp_aggregate_reporting.py` shipped as a standalone scaffold
(see `docs/extensions.md`): a Laplace-mechanism implementation
(`laplace_noise()`, `privatize_counts()`, `mean_absolute_error()`) applied
to two aggregate breakdowns of a scored event set --
`governance_action` distribution and department-level counts -- via
`privatize_report()`, plus `run_epsilon_sweep()` to show the
privacy/utility trade-off across several epsilon values. It already
imported `shade.generate_synthetic_data.generate` and
`shade.governance_score.score_events` from `shade/`, so, like the MCP
monitor before ADR 0003, there was no backwards-layering problem to fix.

The maintainer has asked to integrate this as the third and final of the
three extensions (per the stated one-at-a-time plan), completing the
graduation pattern started in ADR 0002 and continued in ADR 0003.

One structural question needed resolving, flagged as open in ADR 0003's
Consequences section: standalone, `extensions/dp_aggregate_reporting.py`'s
`main()` calls `generate_events()` and `score_events()` itself, producing
a SECOND, independently-generated synthetic event set rather than reusing
whatever set an actual pipeline run already produced. That was a
reasonable design for a standalone script meant to be run on its own, but
it is not the tightest available integration once the module lives
alongside `shade/run_pipeline.py`: the orchestrator already holds a
fully-generated, discovery-scanned, DLP-redacted, governance-scored
`events` list in memory by the time Phase 4 finishes. Re-generating a
second population (even with the same default seed) to privatize would
mean the DP report describes a different run than the one actually
executed -- a real, if subtle, integration seam ADR 0003 predicted would
need its own reasoning rather than a copy-paste of either prior pattern.

## Decision

1. **Move the module to `shade/dp_aggregate_reporting.py`.** It keeps
   `laplace_noise()`, `privatize_counts()`, `mean_absolute_error()`,
   `privatize_report()`, and `run_epsilon_sweep()` exactly as built. Its
   existing imports from `shade.generate_synthetic_data` and
   `shade.governance_score` need no change.
2. **Add one new, opt-in pipeline stage, chained downstream like ADR
   0002's proposer stage -- but chained to this run's own already-scored
   `events`, not a freshly regenerated set.**
   `shade/run_pipeline.py --privatize_governance_report` calls
   `privatize_report(events, epsilon=args.dp_epsilon)` directly on the
   in-memory `events` list Phase 4 already produced (the same object
   `write_csv`'d to `output/scored_events.csv`), after governance scoring
   completes. This is a closer integration than the module's own
   standalone `main()` achieves when run in isolation: the DP report this
   flag produces is guaranteed to describe the exact run that was just
   executed, not a same-seed-but-technically-different second population.
   A new `--dp_epsilon` flag (default `1.0`) controls the single epsilon
   used for this pipeline-stage report; the multi-epsilon
   `run_epsilon_sweep()` capability remains available through the
   module's own CLI (`python shade/dp_aggregate_reporting.py --epsilons
   ...`) rather than being exposed through the pipeline flag, for the
   same reason ADR 0002 kept domain-extension a proposer-CLI-only
   capability: a single, simple pipeline flag is easier to reason about
   than one that can fan out into several reports per run.
3. **Default output path convention switches from `experiments/output/`
   to `output/`** upon graduation, matching the precedent set by ADR 0002
   and ADR 0003: `output/dp_report.json`, written only when the flag is
   passed. The module's own CLI keeps its independent `--out` flag and
   its own `generate_events()`/`score_events()` call for anyone invoking
   it standalone (unchanged behavior there -- the pipeline integration is
   an additional calling convention, not a replacement for the existing
   one).
4. **All scope limits from `docs/extensions.md` are unchanged by
   graduation.** No privacy budget composition tracking across multiple
   releases (this pipeline stage, like the standalone script, spends a
   fresh epsilon as if it were the only query ever made); no DP-SGD
   training mechanism or federated learning; the privacy guarantee is
   real but there is no real sensitive data in this synthetic demo for it
   to protect. Integration changes where the module lives, how tested it
   is, and how tightly it's chained to a real run's own data -- it does
   not, by itself, add budget composition or make any new claim about
   real-world data protection.
5. **Default pipeline behavior and output contract are unchanged.** Not
   passing `--privatize_governance_report` produces byte-for-byte the
   same files the pipeline produced before this ADR (verified below).

## Alternatives considered

- **Keep the module's own regenerate-and-score pattern, just call it from
  the pipeline as a subprocess or fresh function call over `args.n`.**
  Considered and rejected: this was the naive "copy ADR 0002's shape"
  approach, but it would silently produce a DP report describing a
  different (same-size, same-seed, but separately-generated) event
  population than the one the rest of the pipeline's outputs describe --
  a mismatch a careful reader could reasonably interpret as the DP report
  applying to this run, when it technically wouldn't. Chaining to the
  already-in-memory `events` list closes that gap entirely rather than
  papering over it.
- **Structure it as an independent parallel phase, like ADR 0003's MCP
  monitor.** Rejected: unlike the MCP monitor, this module's whole point
  is to privatize an aggregate of THIS run's governance results --
  there's no independent-population argument here the way there was for
  MCP tool-call telemetry (a genuinely different telemetry shape with no
  real relationship to chat-tool events). Treating it as parallel would
  misrepresent it as more independent from the core pipeline than it
  actually is by design.
- **Expose the full multi-epsilon sweep through the pipeline flag.**
  Rejected for the same reason ADR 0002 rejected exposing domain
  extension through the pipeline flag: a single opt-in flag producing one
  report is a narrower, easier-to-reason-about surface than one that can
  produce an arbitrary number of reports controlled by a comma-separated
  string. The sweep capability isn't removed, just kept on the module's
  own CLI.
- **Make the new stage default-on.** Rejected: same scope-creep concern
  ADR 0002 and ADR 0003 both raised and rejected for their respective
  stages. Opt-in preserves the existing, documented output contract.

## Consequences

- `shade/` gains `dp_aggregate_reporting.py`; `extensions/` is now empty
  of the three original standalone prototypes -- all three have
  graduated. `docs/extensions.md` is updated to reflect that DP reporting
  is no longer a standalone extension and that the "three extensions"
  scoping conversation this repository has referenced since it began is
  now fully resolved: all three were built, and all three were later
  integrated, one at a time, each with its own ADR.
- `tests/test_pipeline.py` gains coverage for the DP module: the Laplace
  mechanism produces non-negative integer counts, `mean_absolute_error`
  is computed correctly on a known input, and a monotonicity check
  confirms MAE trends downward as epsilon increases across a fixed
  sweep (formalizing the trade-off the module's docstring and
  `docs/extensions.md` both describe qualitatively).
- The README's module-relationship table and Layout section gain an entry
  for `shade/dp_aggregate_reporting.py`; the self-check test count
  increases again.
- `.github/workflows/test.yml` gains a pipeline run with
  `--privatize_governance_report` alongside the existing
  `--propose_policy_review` and `--include_mcp_monitoring` smoke-test
  steps; the standalone `extensions/` smoke-test block in CI is removed
  entirely, since `extensions/` no longer contains any of the three
  original modules.
- This is the last of the three originally-scoped extensions per the
  maintainer's stated one-at-a-time plan. Any future extension work
  starts a new scoping conversation rather than continuing this series --
  ADRs 0002-0004 together form a complete, honest record of what each
  module was shown to do standalone, what "integration" meant for each
  one specifically (chained-to-fresh-context, parallel-independent, and
  chained-to-in-memory-run respectively), and what none of them claim
  even after graduation.
