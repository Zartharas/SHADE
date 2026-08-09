# ADR 0003: Integrating the MCP tool-call monitor into the core package

## Status

Accepted — 2026-08-09

## Context

`extensions/mcp_tool_call_monitor.py` shipped as a standalone scaffold
(see `docs/extensions.md`): a synthetic MCP (Model Context Protocol)
server/method registry, a second, independently-verified decision matrix
(`method_risk_class x data_sensitivity` -> action), and a generator that
produces synthetic agent tool-call events, redacts their argument text
with `shade/dlp_redact.py`, and classifies each call with
`shade/verify_policy.py`'s `verify_arbitrary_matrix()` -- the same
generalized verifier ADR 0002 relocated into `shade/verify_policy.py` for
exactly this kind of reuse. It was already importing from `shade/` (not
`extensions/`), so, unlike the policy proposer before ADR 0002, there was
no backwards-layering problem to fix first.

The maintainer has asked to integrate this as the second of the three
extensions (per the stated one-at-a-time plan), following the same
graduation pattern as ADR 0002: ADR first, then move the module, then an
opt-in pipeline stage, then tests and docs, then full before/after
verification.

One structural difference from ADR 0002 needed resolving before
"integrate" could mean the same thing here that it meant there:

`shade/policy_proposer.py`'s integration consumes the SAME pipeline run's
own output (`governance_report`'s action distribution) as context --
chaining downstream of existing pipeline data. The MCP monitor has no
equivalent relationship to `output/synthetic_usage.csv` or any other core
pipeline artifact: it generates its own, independent synthetic tool-call
stream (agent tool-calls: server + method + arguments) modeling a
different telemetry shape than the core pipeline's chat-tool prompt-text
events. There is no real sense in which "governance decisions from this
run's chat-tool events" should feed into or gate "synthetic agent
tool-call events" -- the two event populations are deliberately unrelated
representations of two different monitoring surfaces (paper Section 3.5's
distinction between prompt-text telemetry and agent tool-call telemetry).
Forcing a data dependency between them to mimic ADR 0002's shape would
misrepresent that distinction, not integrate it faithfully.

## Decision

1. **Move the module to `shade/mcp_tool_call_monitor.py`.** It keeps its
   synthetic `MCP_METHOD_REGISTRY`, `MCP_DECISION_MATRIX`,
   `generate_synthetic_tool_calls()`, `decide_tool_call()`, and
   `summarize()` exactly as built. Its import of
   `verify_arbitrary_matrix` from `shade.verify_policy` and of
   `redact_text` from `shade.dlp_redact` needs no change, since it
   already pointed at `shade/` rather than `extensions/`.
2. **Add one new, opt-in pipeline stage, structured as a parallel phase,
   not a chained one.** `shade/run_pipeline.py --include_mcp_monitoring`
   runs `generate_synthetic_tool_calls(args.n)` and
   `summarize(...)` as an independent phase alongside (not downstream of)
   the five core phases, reusing `args.n` for scale so a single `--n`
   flag controls the size of both synthetic populations, but drawing no
   data from `events`, `gov_report`, or any other core-phase output. This
   is the intentional structural difference from ADR 0002's
   `--propose_policy_review`, which the "what changes" section of that
   ADR anticipated would need its own reasoning per module, not a
   copy-paste of the same wiring.
3. **Default output path convention switches from `experiments/output/`
   to `output/`** upon graduation, matching the precedent ADR 0002 set
   for `shade/policy_proposer.py`: `output/mcp_tool_calls.csv` and
   `output/mcp_tool_calls_summary.json`, written only when the flag is
   passed. The module's own CLI (`python shade/mcp_tool_call_monitor.py`,
   run standalone) keeps working with its own `--out`/`--summary_out`
   flags for anyone invoking it outside the pipeline.
4. **All scope limits from `docs/extensions.md` are unchanged by
   graduation.** No real MCP server is ever contacted; there is still no
   session-level or multi-step agent plan reasoning (an agent chaining
   several individually-innocuous calls to achieve a risky effect no
   single call would trigger, explicitly out of scope); the
   `method_risk_class` classification is still an author-assigned
   illustrative label, not derived from any real MCP server's documented
   behavior. Integration changes where the module lives, how tested it
   is, and whether the pipeline can invoke it -- it does not, by itself,
   make any of these claims true where they weren't before.
5. **Default pipeline behavior and output contract are unchanged.** Not
   passing `--include_mcp_monitoring` produces byte-for-byte the same
   files the pipeline produced before this ADR (verified below).

## Alternatives considered

- **Chain it downstream of core pipeline data, mirroring ADR 0002
  exactly.** Considered and rejected: there is no real MCP tool-call data
  in the core pipeline's `synthetic_usage.csv` (chat-tool prompt-text
  events) to chain from. Manufacturing a dependency (e.g., deriving
  synthetic tool-call volume from `gov_report`'s action counts) would
  create a fake causal link between two independently-generated synthetic
  populations, misrepresenting the module's actual scope for no real
  integration benefit.
- **Leave it in `extensions/`, add tests only.** Rejected for the same
  reason ADR 0002 rejected it: doesn't satisfy "part of the actual
  pipeline run," which is what "integrate" means in the maintainer's
  stated plan.
- **Make the new phase default-on.** Rejected: would silently grow what a
  default `run_pipeline.py` invocation produces, the same scope-creep
  concern ADR 0002 raised and rejected for the policy-proposer stage.
  Opt-in preserves the existing, documented output contract.
- **Keep the old `experiments/output/` default path even after moving the
  module into `shade/`.** Rejected for consistency: ADR 0002 established
  that graduated modules default to `output/` (the same directory the
  core pipeline writes to) rather than `experiments/output/` (reserved
  for still-standalone extensions and one-off experiment scaffolding).
  Mixing the two conventions inside `shade/` would make the output
  location convention meaningless as a signal of a module's graduation
  status.

## Consequences

- `shade/` gains `mcp_tool_call_monitor.py`; `extensions/` loses it.
  `docs/extensions.md` is updated to reflect that MCP monitoring is no
  longer one of the "two standalone extensions" (now one: DP reporting).
- `tests/test_pipeline.py` gains coverage for the MCP monitor: its
  decision matrix passes the same generalized formal verification the
  module already ran in its own `main()`, its generator produces the
  documented row shape, and (mirroring the policy-proposer regression
  test's spirit) a deliberately broken matrix is confirmed to fail
  verification rather than being silently accepted.
- The README's module-relationship table and Layout section gain an entry
  for `shade/mcp_tool_call_monitor.py`; the "9 checks" description becomes
  higher as new tests are added.
- `.github/workflows/test.yml` gains a pipeline run with
  `--include_mcp_monitoring` alongside the existing
  `--propose_policy_review` smoke-test step, and the standalone
  `extensions/mcp_tool_call_monitor.py` CI invocation is removed as
  redundant (the module is exercised via its new `shade/` location and
  pipeline flag instead).
- If DP aggregate reporting is integrated next (the third and final of
  the three extensions, per the maintainer's stated one-at-a-time plan),
  it gets its own ADR (0004) following this one's numbering. Unlike this
  module, DP reporting privatizes an existing core pipeline artifact
  (`governance_score.py`'s aggregate counts) rather than generating an
  independent population, so its integration shape will likely resemble
  ADR 0002's chained-downstream pattern more than this ADR's parallel-
  phase pattern -- that decision is deferred to ADR 0004, not assumed
  here.
