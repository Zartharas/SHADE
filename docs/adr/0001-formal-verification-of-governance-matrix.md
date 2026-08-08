# ADR 0001: Formal verification approach for the governance decision matrix

## Status

Accepted — 2026-08-08

## Context

`governance_score.py`'s `DECISION_MATRIX` encodes the paper's Section 4.4
decision table as a Python dict keyed on `(tool_risk, data_sensitivity)`,
with `tool_risk in {high, medium, low}` and `data_sensitivity in {critical,
sensitive, public}` — a 3x3 domain, 9 cells, mapping to one of 5 governance
actions. `decide()` falls back to `"ALLOW_WITH_MONITORING"` for any key not
present in the matrix.

Two properties matter for the paper's compliance-mapping argument (Section
7) that code-level auditability is a prerequisite for any claim of
regulatory alignment:

1. **Completeness** — every one of the 9 domain combinations resolves to an
   explicitly authored action, never silently through the fallback. An
   unnoticed gap in the matrix that happens to land on
   `ALLOW_WITH_MONITORING` by fallback rather than by design would be
   invisible in ordinary testing and would misrepresent what was actually
   specified versus what merely happened not to crash.
2. **Non-conflict** — no domain combination is claimed by two different
   actions. This is structurally guaranteed by using a `dict` (a key can
   only hold one value), but "guaranteed by the host language's data
   structure" is a different, weaker claim than "independently verified,"
   and the paper should not conflate the two.

Prior work on formal verification of security/access-control policies
exists and is directly relevant to citing this decision honestly:
Fisler, Krishnamurthi, Meyerovich & Tschantz's Margrave tool verifies and
diffs XACML access-control policies using multi-terminal binary decision
diagrams (ICSE 2005, https://cs.brown.edu/people/kfisler/Pubs/icse05.pdf),
and Hughes & Bultan extended this line of work with a direct SAT-based
encoding of XACML policy verification (STTT 2008, DOI
10.1007/s10009-008-0087-9). Both were built because real access-control
policies have combinatorially large or structurally recursive rule sets
(boolean policy combinators, hierarchical roles, wildcard attributes) where
exhaustive enumeration is infeasible and a symbolic/SAT encoding is the
only tractable approach.

SHADE's matrix does not have that shape. It is a flat, total function over
a 9-element finite domain with no boolean combinators, no recursion, and no
attribute hierarchy.

## Decision

Verify the matrix by **exhaustive enumeration over the finite domain**,
not a SAT/SMT solver.

Concretely: `verify_policy.py` enumerates all 9 `(tool_risk,
data_sensitivity)` pairs and asserts, for each one, that `DECISION_MATRIX`
contains an explicit entry (completeness — the fallback path is never
exercised) and that the corresponding action is a member of the fixed
5-action vocabulary (well-formedness). It also asserts structurally that
`DECISION_MATRIX` has no duplicate keys and exactly 9 entries (non-conflict
and exact coverage, respectively — duplicate dict keys are impossible in
Python, so this check exists as a machine-checked assertion the module
produces, not just an appeal to "Python guarantees this").

For a finite state space this small, exhaustive enumeration is not an
approximation of model checking — it *is* explicit-state model checking: it
visits every reachable state and checks the property in each, which is a
sound and complete decision procedure by construction. There is no
completeness gap that a SAT solver would close that enumeration does not
already close identically, and no case where SAT would be exponentially
faster on a search space of size 9.

## Alternatives considered

- **Z3 / SMT encoding.** Would encode `tool_risk` and `data_sensitivity` as
  finite-domain (enum) variables and assert `forall` completeness and
  `exists-unique` non-conflict as SMT formulas, discharged by Z3. Rejected
  for this table: it adds a real dependency (`z3-solver`, not currently
  installed in this environment or listed in `requirements.txt`) that
  conflicts with the project's stated zero-budget/dependency-light
  positioning, for a verification guarantee identical to enumeration on a
  domain this size. It would be the right choice if the matrix grew to
  include boolean policy combinators, more than a handful of ordinal risk
  levels, or cross-cutting exception rules — noted below as a trigger
  condition for revisiting this ADR.
- **Margrave-style BDD/XACML tooling.** Rejected as substantial
  over-engineering for a 9-cell table; XACML's policy-combination algebra
  (permit-overrides, deny-overrides, first-applicable) has no analogue here
  since there is exactly one flat table with no combinators.
- **Property-based testing (Hypothesis) instead of exhaustive check.**
  Rejected because the domain is small enough to enumerate exactly;
  property-based testing over a random sample would be a weaker guarantee
  (probabilistic coverage) for more code than the exhaustive version.

## Consequences

- `verify_policy.py` has no new dependencies; it runs with the standard
  library, consistent with `requirements.txt` and the project's zero-budget
  framing.
- The verification is provably complete for the current 3x3 domain. If the
  matrix is later extended (e.g., a fourth risk tier, or rules that compose
  multiple policies), this ADR's reasoning no longer automatically holds
  and should be revisited — at that point the SAT/SMT alternative above
  becomes the more defensible choice, and this ADR says so explicitly so a
  future contributor doesn't have to rediscover the trade-off.
- The paper/follow-up work should describe this as "exhaustive verification
  over the finite decision domain (equivalent to explicit-state model
  checking at this scale)," not as "SAT-based formal verification" — the
  latter would overclaim the technique actually used.
- `test_pipeline.py` calls `verify_policy.run_all_checks()` so CI fails
  loudly if the matrix is ever edited into an incomplete or malformed
  state, rather than relying on the pre-existing test that just
  re-asserted the same table.

## References

- Fisler, K., Krishnamurthi, S., Meyerovich, L. A., & Tschantz, M. C.
  (2005). Verification and change-impact analysis of access-control
  policies. *ICSE 2005*. https://cs.brown.edu/people/kfisler/Pubs/icse05.pdf
- Hughes, G., & Bultan, T. (2008). Automated verification of access control
  policies using a SAT solver. *International Journal on Software Tools
  for Technology Transfer*, 10(6). DOI: 10.1007/s10009-008-0087-9
