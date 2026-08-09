# Shadow AI vs. Shadow IT: a short comparative note

This note distinguishes Shadow AI from the older, better-studied Shadow IT
category, grounded in two sources: DART (Sebastian, 2026, *Technological
Forecasting and Social Change*) and Silic, Silic & Kind-Truller (2025,
*Strategic Change*). Both are drawn from their published abstracts only
(full text of both is paywalled and was not accessed for this note); claims
below are scoped to what those abstracts state, not inferred beyond them.

## What Shadow IT is

Shadow IT is the established category this literature builds on: employees
adopting unsanctioned software, hardware, or cloud services (personal
Dropbox accounts, unapproved SaaS tools, unmanaged devices) outside IT's
visibility and approval process. The governance response that emerged over
roughly two decades of Shadow IT research and tooling -- network/endpoint
discovery, CASB-style inventory, sanctioning workflows -- is the model
SHADE's `shade/discovery_scan.py` and `config/known_endpoints.yaml` are
structurally descended from: find what's running, classify it,
sanction-or-block it.

## What both cited sources say is different about Shadow AI

Silic, Silic & Kind-Truller's abstract states the point most directly:
Shadow AI "shares roots with Shadow IT, its generative, opaque, and
autonomous nature introduces novel risks related to data privacy,
algorithmic bias, hallucination, and governance drift" -- i.e., the
*category* is continuous with Shadow IT, but specific properties of
generative/agentic AI change what governing it requires.

DART's abstract makes a related but distinct claim: Shadow AI's
contribution "lies in distinguishing Shadow AI from traditional Shadow IT
by showing how everyday, efficiency-driven AI use embeds risk into routine
knowledge work" and that, "by externalizing organizational knowledge into
adaptive AI systems, Shadow AI introduces risks that extend beyond
technical non-compliance to cognitive dependence and governance erosion."

Putting the two together, three concrete differences both sources point to:

1. **What's being risked.** Shadow IT risk is largely about the tool
   itself (unpatched software, uncontrolled data storage location, license
   compliance). Shadow AI risk, per DART, is about what happens to the
   *content* people put into the tool -- disclosure, and (DART's specific
   contribution) *knowledge dilution*: organizational knowledge work being
   externalized into systems the org doesn't control.
2. **Static vs. adaptive.** A Shadow IT tool (an unsanctioned file-sync
   client, say) behaves the same way every time. Silic et al.'s "adaptive"
   framing and DART's "Ethical Black Box Problem" construct both point to
   generative/agentic tools behaving differently across uses in ways that
   are hard to audit after the fact -- a discovery-and-inventory response
   (adequate for Shadow IT) doesn't address this by itself.
3. **Detection difficulty.** Silic et al.'s interviews describe
   organizational structures "failing to regulate" Shadow AI's spread, and
   their proposed mitigations -- "AI tool registries, role-specific
   training, internal audits, and escalation protocols" -- are explicitly
   broader than technical discovery alone. This matches SHADE's own
   Discover-then-Govern ordering (see `docs/theory.md`'s
   "visibility/implementation gap" section) but also implies that
   discovery/inventory (what `shade/discovery_scan.py` and
   `config/known_endpoints.yaml` illustrate) is necessary, not sufficient
   -- consistent with why SHADE's pipeline doesn't stop at Discover and
   adds a Govern stage with explainable, per-decision reasoning
   (`decide_with_reason()`, see the Phase 2 work in
   `docs/adr/0001-formal-verification-of-governance-matrix.md`).

## Where SHADE sits in this distinction

SHADE's architecture is explicitly a Shadow-IT-style discovery-plus-policy
pipeline (`config/known_endpoints.yaml` is a hand-maintained tool registry,
structurally similar to a CASB inventory) extended with governance logic
aimed at the Shadow-AI-specific risk both sources describe: `shade/dlp_redact.py`
targets disclosure risk directly (DART's Unintentional Disclosure Risk
construct, see `docs/theory.md`), and the explainability work in
`shade/governance_score.py` is a narrow, code-level response to the "opaque"/
"black box" characterization both sources apply to Shadow AI specifically
-- SHADE's own governance layer now explains itself, as a small
counter-example to the pattern both papers describe, though this in no way
claims to reduce opacity in the underlying AI tools users interact with.

What SHADE does *not* address, and should not be read as addressing, per
this comparison: Knowledge Dilution Phenomenon (no measurement of
organizational knowledge externalization), Trust-Dependence Paradox or
Organizational Feedback Loops (both require longitudinal/behavioral data
SHADE's point-in-time synthetic events don't have), and governance drift
over time (SHADE evaluates a fixed decision matrix at a point in time, not
how governance erodes or adapts). See `docs/theory.md`'s DART mapping
section for the full breakdown of what does and doesn't transfer.

## References

- Sebastian, G. (2026). Digital shadow AI risk theory (DART): A framework
  for managing data disclosure and privacy risks of AI tools at work.
  *Technological Forecasting and Social Change*, 229.
  DOI: 10.1016/j.techfore.2026.124697
- Silic, M., Silic, D., & Kind-Truller, K. (2025). From Shadow IT to Shadow
  AI: Threats, risks and opportunities for organizations. *Strategic
  Change*. (Mixed-methods: 140 survey responses, 10 executive interviews.)
