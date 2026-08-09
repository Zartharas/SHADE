# Optional extensions: scope and status

Three extensions were built after the core project (Phases 1-5), against
the original scoping rule that only one should be attempted, "properly
scoped... not the full research-paper version." That rule was explicitly
overridden by request; all three are implemented here as solo-researcher-
scoped prototypes, not as finished, defensible research contributions in
their own right. This document is the honest accounting of what that means
for each.

All three live in `extensions/`, are standalone (importable and runnable
independently), and are **not wired into `run_pipeline.py` or
`test_pipeline.py`** -- they don't change the core pipeline's documented
behavior, and none of their claims should be read as claims about the core
SHADE pipeline itself.

## 1. LLM-based dynamic policy generation (`extensions/llm_policy_proposer.py`)

No live LLM API call is made anywhere in this repository -- SHADE is
offline/zero-budget by design, and wiring in a real API would break that
property and cost real money. What's implemented instead: a pluggable
`PolicyProposerBackend` interface with one shipped implementation
(`HeuristicMockBackend`, deterministic and offline) that produces a
plausible-shaped policy proposal, which then passes through a **formal
verification gate** (generalized from `verify_policy.py`'s method to an
arbitrary two-axis domain) before being written out as a candidate for
human review. It is never auto-applied to `governance_score.py`.

**What this demonstrates:** the propose -> verify -> human-review pipeline
mechanics, and that the verification gate genuinely rejects bad proposals
(tested directly with a deliberately broken backend that omits a cell and
uses an invalid action label -- both were correctly caught).

**What this does NOT demonstrate:** anything about real LLM policy-
proposal quality. That's a separate research question requiring a real
API call and its own evaluation, explicitly left as future work.

## 2. Agentic-AI-governance / MCP tool-call monitoring (`extensions/mcp_tool_call_monitor.py`)

Extends SHADE's monitoring concept from chat-tool prompt text to agent
tool-calls (the MCP telemetry shape: server + method + arguments), with
governance decisions based primarily on method-level risk classification
(read/write/execute) rather than only regex-detectable content in
arguments -- reusing `dlp_redact.py`'s patterns as a secondary signal. Uses
a new, separately verified decision matrix
(`method_risk_class x data_sensitivity`), formally checked with the same
shared verification helper (`extensions/_verification_core.py`) the first
extension uses, demonstrating the verification approach generalizes to a
second governance table.

**What this does NOT demonstrate:** session-level or multi-step agent plan
reasoning (an agent chaining several individually-innocuous calls to
achieve a risky effect no single call would trigger) -- a real and harder
problem, explicitly out of scope here. All events are synthetic; no real
MCP server is ever contacted.

## 3. Privacy-preserving detection prototype (`extensions/dp_aggregate_reporting.py`)

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

## Common thread across all three

Every extension reuses rather than reimplements core-pipeline logic where
possible (dlp_redact.py's patterns, the exhaustive-enumeration
verification method from ADR 0001, generate_synthetic_data.py's event
generator) and is explicit about what it does not claim. None of them
should be cited as validated research contributions without the caveats
above; they are scaffolds for future, separately-scoped work.
