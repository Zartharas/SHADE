# Optional extensions: scope and status

Three extensions were built after the core project (Phases 1-5), against
the original scoping rule that only one should be attempted, "properly
scoped... not the full research-paper version." That rule was explicitly
overridden by request; all three were implemented as solo-researcher-
scoped prototypes, not as finished, defensible research contributions in
their own right.

**Update:** the LLM policy proposer and the MCP tool-call monitor have
since graduated out of this document. The proposer is now
`shade/policy_proposer.py` (see
`docs/adr/0002-integrating-llm-policy-proposer.md`); the MCP monitor is
now `shade/mcp_tool_call_monitor.py` (see
`docs/adr/0003-integrating-mcp-tool-call-monitor.md`). Both are tested by
`tests/test_pipeline.py` and wired into `shade/run_pipeline.py` as
opt-in stages -- the proposer chains downstream of a run's own governance
results, while the MCP monitor runs as an independent parallel phase,
since its synthetic tool-call stream has no real relationship to the core
pipeline's chat-tool events (see ADR 0003 for why). DP aggregate reporting
remains a standalone extension, described below, and this document is
still the honest accounting of what it does and doesn't demonstrate. Per
the maintainer's stated plan (integrate one at a time, test, then move to
the next), DP reporting is the last of the three and is a candidate for
the same treatment later, with its own ADR (0004) when/if that happens.

The remaining one lives in `extensions/`, is standalone (importable and
runnable independently), and is **not wired into `shade/run_pipeline.py`
or `tests/test_pipeline.py`** -- it doesn't change the core pipeline's
documented behavior, and none of its claims should be read as claims
about the core SHADE pipeline itself.

```mermaid
flowchart TB
    subgraph core["Core pipeline (tested, wired into shade/run_pipeline.py)"]
        GS[shade/governance_score.py<br/>DECISION_MATRIX] --> VP[shade/verify_policy.py<br/>exhaustive verification + verify_arbitrary_matrix]
        DR[shade/dlp_redact.py<br/>PATTERNS]
        GEN[shade/generate_synthetic_data.py]
        PP[shade/policy_proposer.py<br/>propose -> verify -> human review<br/>opt-in pipeline stage, chained]
        MCP[shade/mcp_tool_call_monitor.py<br/>agent tool-call telemetry<br/>opt-in pipeline stage, parallel]
    end
    subgraph ext["extensions/ (standalone, CI-smoke-tested only)"]
        DP[dp_aggregate_reporting.py<br/>Laplace mechanism on aggregates]
    end
    PP --> VP
    MCP --> VP
    MCP -.reuses.-> DR
    DP -.privatizes output of.-> GS
    GEN -.reused by.-> DP
```

## Graduated: LLM-based dynamic policy generation (now `shade/policy_proposer.py`)

No live LLM API call is made anywhere in this repository -- SHADE is
offline/zero-budget by design, and wiring in a real API would break that
property and cost real money. What's implemented instead: a pluggable
`PolicyProposerBackend` interface with one shipped implementation
(`HeuristicMockBackend`, deterministic and offline) that produces a
plausible-shaped policy proposal, which then passes through a **formal
verification gate** (`shade/verify_policy.py`'s `verify_arbitrary_matrix()`,
generalized to an arbitrary two-axis domain) before being written out as a
candidate for human review. It is never auto-applied to
`shade/governance_score.py` -- this is now a regression-tested property
(`test_policy_proposer_never_mutates_decision_matrix`), not just a design
intent.

**What integration added:** an opt-in `--propose_policy_review` flag on
`shade/run_pipeline.py` that runs the proposer against the run's own
governance action distribution (real pipeline context, not just a
CLI-supplied string), off by default so the documented default output
contract is unchanged. Three tests in `tests/test_pipeline.py`: the normal
case passes verification, a deliberately broken backend is rejected, and
`DECISION_MATRIX` is confirmed byte-identical before/after both.

**What this still does NOT demonstrate, even integrated:** anything about
real LLM policy-proposal quality. That's a separate research question
requiring a real API call and its own evaluation, still explicitly future
work -- integration changed where the module lives and how tested it is,
not what backend it uses.

## Graduated: agentic-AI-governance / MCP tool-call monitoring (now `shade/mcp_tool_call_monitor.py`)

Extends SHADE's monitoring concept from chat-tool prompt text to agent
tool-calls (the MCP telemetry shape: server + method + arguments), with
governance decisions based primarily on method-level risk classification
(read/write/execute) rather than only regex-detectable content in
arguments -- reusing `shade/dlp_redact.py`'s patterns as a secondary signal. Uses
a new, separately verified decision matrix
(`method_risk_class x data_sensitivity`), formally checked with the same `shade/verify_policy.py`'s
`verify_arbitrary_matrix()` that `shade/policy_proposer.py` uses,
demonstrating the verification approach generalizes to a second
governance table.

**What integration added:** an opt-in `--include_mcp_monitoring` flag on
`shade/run_pipeline.py` that runs the synthetic tool-call generator as an
INDEPENDENT parallel phase (reusing `--n` for scale, but not chained to
this run's chat-tool events or governance results -- see
`docs/adr/0003-integrating-mcp-tool-call-monitor.md` for why that
structural choice differs from the policy proposer's chained integration),
off by default so the documented default output contract is unchanged.
Three tests in `tests/test_pipeline.py`: the shipped decision matrix
passes formal verification, a deliberately broken matrix is correctly
rejected, and the generator's output rows are confirmed well-formed and
internally consistent with `decide_tool_call()`.

**What this still does NOT demonstrate, even integrated:** session-level
or multi-step agent plan reasoning (an agent chaining several
individually-innocuous calls to achieve a risky effect no single call
would trigger) -- a real and harder problem, explicitly out of scope
here. All events are synthetic; no real MCP server is ever contacted.
Integration changed where the module lives, how tested it is, and whether
the pipeline can invoke it -- it does not change any of these scope
limits.

## 1. Privacy-preserving detection prototype (`extensions/dp_aggregate_reporting.py`)

Applies the Laplace mechanism (epsilon-differential privacy for count
queries) to SHADE's **aggregate reporting** outputs (governance action
distribution, department-level breakdowns) -- not to the per-event
classification step. That's a deliberate reinterpretation of the original
scoping conversation's "differential privacy on the classification step,"
documented here rather than done silently: `decide()` is a deterministic
lookup over a verified, complete table, so there's no statistical query
there for DP to protect; aggregate count release, where small-group counts
can leak individual-level information, is where the mechanism actually has
something to do.

**What this demonstrates:** a working, correctly-implemented Laplace
mechanism with a measured privacy/utility trade-off (mean absolute error
across four epsilon values on 2000 synthetic events, monotonically
decreasing as epsilon increases, as the mechanism's theory predicts).

**What this does NOT demonstrate:** privacy budget composition across
multiple releases (each run spends a fresh epsilon as if it were the only
query ever made -- a real deployment publishing several differently-sliced
aggregates would need cumulative budget accounting this prototype doesn't
implement), any DP-SGD training mechanism, or federated learning (the
scoping conversation's other listed option, not attempted -- picking both
would have re-violated the "one, properly scoped" principle a second time).

## Common thread

Every module here (graduated or still standalone) reuses rather than
reimplements core-pipeline logic where possible (shade/dlp_redact.py's
patterns, the exhaustive-enumeration verification method from ADR 0001,
shade/generate_synthetic_data.py's event generator) and is explicit about
what it does not claim. Graduating a module changes where it lives and how
rigorously it's tested; it does not, by itself, change what it's actually
been shown to do -- that still has to be earned separately, as the "what
integration added" vs. "what it still does NOT demonstrate" split above
for the policy proposer is meant to make clear.
