# ADR 0005: DP privacy budget composition

## Status

Accepted — 2026-08-09

## Context

`shade/dp_aggregate_reporting.py`'s own docstring, since ADR 0004, has
stated this limitation plainly:

> No privacy BUDGET COMPOSITION tracking across multiple releases. Each
> call to privatize_report() spends a fresh epsilon as if it were the
> only query ever made against the dataset... A real deployment would
> need it.

Re-reading `privatize_report()` while scoping this ADR surfaced that the
gap is narrower, and more concrete, than the docstring's own framing
suggested — it isn't only a cross-call concern. `privatize_report()`
already makes TWO releases from the SAME underlying `rows` in a single
call: an `action_distribution` count release and a `department_distribution`
count release, each independently privatized via `privatize_counts()` at
the SAME nominal `epsilon`.

By the basic (sequential) composition theorem (Dwork & Roth, 2014, *The
Algorithmic Foundations of Differential Privacy*, Theorem 3.16), releasing
two epsilon-DP results computed from the same data costs `2 * epsilon`
of privacy budget in total, not `epsilon`. Before this ADR,
`privatize_report(rows, epsilon=1.0)` silently spent 2.0 epsilon of real
privacy budget while its own output only ever reported `"epsilon": 1.0`
— a genuine under-statement of the true privacy cost, not a hypothetical
one, and not something a caller reading the report's output could have
noticed. This is a correctness bug in the DP accounting, not merely a
missing nice-to-have.

Separately, the docstring's literal complaint — no tracking across
*multiple calls* to `privatize_report()` against overlapping data (e.g.
releasing a report today, then another tomorrow, from data that still
overlaps) — remains a real, distinct gap once the intra-report bug above
is fixed. Both needed addressing; they are related (both are instances of
the same composition theorem) but not the same fix.

## Decision

**1. Reinterpret `epsilon` in `privatize_report()` as the TOTAL budget for
the whole report, split across its two releases.**

`privatize_report(rows, epsilon, ...)` now computes
`per_query_epsilon = epsilon / 2` and uses that value for both the
action-distribution and department-distribution Laplace releases. Their
combined cost under basic composition is exactly `epsilon`, matching what
the report claims to have spent. This is a genuine behavior change — the
same nominal `epsilon` value now produces noisier individual releases
than before (each release gets half the privacy budget it used to) — so
the module's measured MAE numbers change too; see Consequences below for
the corrected figures.

This is treated as a bug fix, not new opt-in functionality, because the
old behavior mis-stated the true privacy cost of an already-existing
code path. It is safe to change unconditionally (rather than gating it
behind a new flag) because `--privatize_governance_report` on
`shade/run_pipeline.py` was already opt-in (ADR 0004) and off by default
— correcting its internal accounting when a caller explicitly requests it
does not touch the pipeline's default, untouched output contract that
ADRs 0002–0004 have each protected.

`privatize_report()`'s returned dict now reports `total_epsilon`,
`per_query_epsilon`, and a `composition_note` string explaining the
split in the output itself, so a reader of the JSON report doesn't have
to know this ADR exists to understand what was actually spent.

**2. Add `PrivacyBudgetTracker` for cross-release composition.**

A new class in the same module:

- `PrivacyBudgetTracker(total_budget)` — construct with the total epsilon
  a dataset is allowed to have spent against it, ever.
- `.spend(epsilon, label=None)` — records one release's cost; raises
  `PrivacyBudgetExceededError` if the cumulative total would exceed
  `total_budget`, BEFORE that release's noise is computed. Fails closed,
  the same pattern this project's other guardrails already use
  (`shade/verify_policy.py`'s `verify_arbitrary_matrix()`,
  `shade/policy_proposer.py`'s formal-verification gate): the check
  actually blocks the over-budget case rather than merely documenting
  that callers shouldn't do it.
- `.remaining()` and `.history` (a list of `{label, epsilon,
  cumulative_after}` records) for auditability.

`privatize_report()` takes optional `budget_tracker` and `label`
arguments; when given, the report's TOTAL epsilon is spent against the
tracker before either release is computed, and the returned report
includes a `budget_tracker_state` block (`spent`, `remaining`,
`total_budget`).

`shade/dp_aggregate_reporting.py`'s standalone CLI gains an optional
`--budget_cap` flag that demonstrates the tracker against the single
`detail_at_median_epsilon` report the CLI produces (not the `--epsilons`
sweep, deliberately — see below).

**3. The `--epsilons` sweep is explicitly NOT composed against a
tracker.**

`run_epsilon_sweep()` evaluates several alternative epsilon choices to
show the privacy/utility trade-off — it is a what-if comparison across
options, only one of which would actually be deployed. Treating all
swept values as if they were real sequential releases and composing
their cost would misrepresent an evaluation tool as an audit of actual
spend. This distinction is stated in `--budget_cap`'s own `--help` text
and in the module's docstring, not left implicit.

**4. What is deliberately NOT built.**

A persistent, cross-process-invocation budget ledger (e.g. a state file
on disk that survives separate `python3 shade/run_pipeline.py` runs on
different days, so a real deployment could enforce a rolling weekly or
monthly budget across independently-scheduled pipeline runs) is real,
useful future work that this ADR does not attempt. `PrivacyBudgetTracker`
as built only tracks spend within the lifetime of the Python process
that constructs it — good enough to demonstrate and test the composition
theorem correctly, not sufficient on its own for a production multi-run
deployment. Stated here rather than silently scoped out.

## Alternatives considered

- **Leave `epsilon` as per-query and only add a docstring note
  explaining the true 2x cost.** Rejected: this project's own standard
  (ADR 0001 onward) is that guardrails and accounting should be
  correct by construction, not correct-if-the-reader-does-arithmetic.
  A caller who trusts the reported `"epsilon"` field deserves it to be
  the true cost.
- **Advanced composition (Dwork, Rothblum, Vadhan, 2010) or a
  moments-accountant-style bound instead of basic composition.**
  Rejected for now: these give tighter (smaller) total-epsilon bounds
  for the same number of releases, but add real complexity for a
  prototype expected to make at most a handful of releases per dataset.
  The same "simplest method that is correct at the actual scale"
  reasoning ADR 0001 used when choosing brute-force verification over an
  SMT solver for the 6x6 governance matrix applies here. Documented as a
  known, reasonable place to upgrade if `PrivacyBudgetTracker` is ever
  asked to track many releases rather than a few.
- **Silently keep both releases at full `epsilon` each but report
  `"epsilon": 2 * epsilon` instead.** Rejected: this "fixes" the honesty
  of the number but doesn't fix the actual privacy behavior — a caller
  asking for `epsilon=1.0`-level privacy would still receive an
  actually-more-private (lower true epsilon per query) or the reverse,
  depending on framing, and either way the caller no longer controls
  what they asked to control. Splitting the budget so the caller's
  requested total is what actually gets spent is the more useful
  contract.
- **Build the persistent cross-invocation ledger now.** Rejected for
  this pass: real value, but meaningfully larger scope (a state file
  format, concurrency/locking considerations if two pipeline runs
  overlap, a retention/reset policy) that deserves its own scoping
  conversation rather than being folded into closing this specific
  docstring-flagged gap. Flagged explicitly as future work above.

## Consequences

- `shade/dp_aggregate_reporting.py`'s `privatize_report()` signature
  gains `budget_tracker=None, label=None` (backward compatible — both
  default to the old no-tracking behavior); its return dict's `epsilon`
  key is replaced by `total_epsilon` and `per_query_epsilon` plus a
  `composition_note` string. This is a breaking change to the report's
  JSON shape for any code reading the old `"epsilon"` key directly — a
  full-repo check confirmed nothing else in `shade/`, `tests/`, or
  `scripts/` read that key (`run_epsilon_sweep()` and callers only read
  `action_distribution`/`department_distribution`'s nested
  `mean_absolute_error`), so nothing else needed updating.
- New `PrivacyBudgetTracker` and `PrivacyBudgetExceededError` classes,
  covered by new regression tests confirming: correct accumulation
  across calls, rejection of an over-budget spend before any noise is
  computed, and acceptance of a spend landing exactly at the budget
  (float-tolerance handled).
- **Measured numbers change** (this is a real behavior change, not a
  cosmetic one — documented in `docs/benchmark.md` with corrected
  values): at `epsilon=1.0`, seed=42, the action-distribution MAE
  measured previously as 1.2 (both n=500 and n=5,000) is now 2.2 at both
  n values — each release now gets `epsilon/2 = 0.5`, doubling the
  Laplace noise scale (`sensitivity/epsilon`) relative to before. The
  qualitative finding this was illustrating (absolute MAE is flat across
  n while relative error shrinks 10x from n=500 to n=5,000) still holds
  with the corrected numbers (1.2%→2.2% relative at n=500,
  0.12%→0.22% at n=5,000) — only the absolute figures moved.
- `run_pipeline.py --dp_epsilon`'s help text is updated to state
  explicitly that the value is a TOTAL per-report budget, not a
  per-release epsilon.
- `docs/benchmark.md`, `docs/extensions.md`, and this module's own
  docstring are updated to reflect the corrected accounting and point to
  this ADR; ADR 0004 is not rewritten (it accurately describes what was
  true at the time) but is cross-referenced from here.
- The persistent cross-invocation ledger remains explicitly unbuilt —
  noted as the natural next step if a future deployment needs it, not
  silently implied to already exist.
