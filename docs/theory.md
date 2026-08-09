# Theoretical positioning

This document maps SHADE's four pipeline stages against two established
governance frameworks (NIST AI RMF, ISO/IEC 42001) and against DART's six
risk constructs, and states plainly where a mapping is genuine versus where
forcing one would misrepresent what SHADE actually does. SHADE is a small,
synthetic-data prototype accompanying the paper; it is not an
implementation of any of the frameworks below, and this document should not
be read as a compliance claim.

**Source note.** NIST AI RMF 1.0 and its function definitions are drawn
from NIST's own AI RMF materials (nist.gov/itl/ai-risk-management-framework,
airc.nist.gov/airmf-resources/playbook). ISO/IEC 42001:2023 is described
from ISO's own standard listing (iso.org/standard/42001). DART is drawn
from its published abstract (Sebastian, G. (2026). Digital shadow AI risk
theory (DART): A framework for managing data disclosure and privacy risks
of AI tools at work. *Technological Forecasting and Social Change*, 229.
DOI: 10.1016/j.techfore.2026.124697) and an earlier preprint abstract
(research.google/pubs/...dart...). The full published text is behind a
ScienceDirect paywall and was not accessed for this document; all DART
claims below are scoped to what the abstract itself states. Note the
preprint abstract reports two survey waves (N=374, N=179) and 7/8
hypotheses supported, while the published abstract reports three waves
(N=374, N=179, N=220) and 6/8 supported -- the published version is treated
as authoritative here, and the discrepancy is flagged rather than silently
resolved.

## SHADE's four stages, briefly

`shade/generate_synthetic_data.py` (N/A -- data generation only) feeds:
1. **Discover** (`shade/discovery_scan.py`) -- reads a ground-truth label and
   reports sanctioned/unsanctioned tool-use split.
2. **Classify** (`shade/dlp_redact.py` + the `tool_risk`/`data_sensitivity`
   labels used downstream) -- regex-based sensitive-pattern detection and
   risk-tier labeling.
3. **Govern** (`shade/governance_score.py`) -- the Section 4.4 decision matrix,
   now with formal verification (`shade/verify_policy.py`) and per-decision
   explanations (`decide_with_reason()`).
4. **Validate** (`shade/build_dashboard.py`, `tests/test_pipeline.py`,
   `VALIDATION_REPORT.md`) -- internal consistency checks and a static
   dashboard, not independent real-world validation (see
   `docs/benchmark.md` for exactly what is and isn't measured here).

## Mapping to NIST AI RMF 1.0

NIST AI RMF 1.0 is organized around four functions: **GOVERN** (spans the
whole organization, establishes accountability and policy, and is the
function the other three sit under), **MAP** (frames the AI system, its
context, and stakeholders), **MEASURE** (assesses and benchmarks risk
against defined categories), and **MANAGE** (allocates resources and
applies controls to treat risk).

| SHADE stage | Closest NIST function | Why | Where it doesn't fit |
|---|---|---|---|
| Discover | MAP | Establishing an inventory of AI tools in use and their sanctioned/unsanctioned status is squarely a context-framing activity -- you cannot map risk for a system you haven't identified. | SHADE's discovery reads a pre-generated ground-truth label rather than performing independent detection (network telemetry, endpoint agents), so it only illustrates the *output* of a MAP-relevant activity, not the activity itself; see the README's module-relationship table. |
| Classify | MAP / MEASURE (split) | Assigning `tool_risk` and `data_sensitivity` labels, and detecting sensitive-pattern content, combines MAP's categorization work with MEASURE's risk-benchmarking intent. | SHADE's classification is regex pattern-matching plus static config lookups, not the kind of quantitative risk benchmarking MEASURE describes (e.g. bias/robustness metrics against a defined AI system). |
| Govern | MANAGE, *not* NIST GOVERN | This is the most important mismatch to state plainly: SHADE's "Govern" phase applies pre-set controls (block/allow/redact) to individual events -- that is NIST's MANAGE (resource allocation and control application), not NIST's GOVERN (organization-wide accountability structures, policy-setting culture, oversight roles). The shared word "govern" is a naming coincidence between the paper's stage labels and NIST's function names, not a substantive equivalence. | SHADE has no representation at all of NIST GOVERN's actual scope -- accountability structures, risk-tolerance policy-setting, organizational culture. That's out of scope for a code prototype and shouldn't be implied by the stage name. |
| Validate | Weak/partial MEASURE | Both involve checking something against a standard, but NIST MEASURE assesses the risk of a production AI *system*; SHADE's Validate stage checks the *pipeline's own code* (decision-matrix completeness, DLP pattern coverage) against its own synthetic ground truth. | Should not be described as MEASURE in the NIST sense without this caveat -- see `docs/benchmark.md`, which exists specifically to prevent this stage from being overclaimed as real-world risk measurement. |

## Mapping to ISO/IEC 42001:2023

ISO/IEC 42001 specifies requirements for an organizational AI Management
System (AIMS): risk assessment, AI system impact assessment, lifecycle
management, third-party/supplier oversight, and continuous monitoring and
improvement (iso.org/standard/42001).

SHADE is a single prototype pipeline, not an organizational management
system, so this mapping is necessarily thinner than the NIST one. The
genuine points of contact: `config/known_endpoints.yaml`'s tool registry
is a narrow illustration of the kind of AI-system inventory an AIMS would
maintain at organizational scale; the governance decision matrix and its
formal verification illustrate, at prototype scale, the kind of documented,
auditable control ISO/IEC 42001 asks for; and `VALIDATION_REPORT.md`
gestures at (without implementing) the standard's continuous-monitoring
expectation. SHADE does not implement supplier oversight, does not cover
organizational roles/responsibilities, and makes no certification-relevant
claim -- an AIMS is an organizational management system, and nothing here
should be read as evidence of, or a step toward, ISO/IEC 42001 conformance.

## Mapping to DART's six constructs

DART (Sebastian, 2026) identifies six constructs: Unintentional Disclosure
Risk, Trust-Dependence Paradox, Data Sovereignty Conflict, Knowledge
Dilution Phenomenon, Ethical Black Box Problem, and Organizational Feedback
Loops.

**Genuinely applicable:**

- **Unintentional Disclosure Risk** maps directly onto `shade/dlp_redact.py`'s
  purpose -- detecting API-key-shaped strings, emails, SSN-shaped strings,
  and phone numbers in prompt text is a concrete, narrow instance of
  exactly this construct.
- **Ethical Black Box Problem** is the construct this session's Phase 2
  work (`decide_with_reason()`, `docs/adr/0001-...md`) most directly
  engages with, in the mitigating direction: DART's abstract frames
  opacity of AI-mediated decisions as a risk; SHADE's governance layer now
  explicitly counters analogous opacity in its *own* decisioning by
  attaching a reason to every action and formally verifying the underlying
  rule table. This is a genuine conceptual link, not a claim that SHADE
  measures or reduces opacity in the *AI tools* users interact with (which
  DART's construct is actually about) -- SHADE's governance layer is
  external to those tools.

**Thematically relevant but not implemented:**

- **Knowledge Dilution Phenomenon** connects directly to the paper's own
  "Shadow AI as organizational knowledge risk" framing, but SHADE has no
  code artifact that measures or models knowledge dilution -- there is no
  construct in the pipeline analogous to it. Flagged here as a conceptual
  alignment between the paper's framing and DART's construct, not
  something SHADE operationalizes.

**Not applicable -- do not force:**

- **Trust-Dependence Paradox** and **Organizational Feedback Loops** are
  both behavioral/longitudinal constructs DART measures via multi-wave
  survey data on how employees relate to AI tools over time. SHADE
  processes point-in-time synthetic event data and has no behavioral or
  temporal model; there is no honest mapping here.
- **Data Sovereignty Conflict** has only a thin, incidental connection: a
  couple of entries in `config/known_endpoints.yaml` carry notes like
  "foreign-hosted" or "no verifiable data-handling disclosure," but SHADE
  does not model data sovereignty as a first-class variable anywhere in
  the pipeline (it isn't a field alongside `tool_risk`/`data_sensitivity`).
  Worth noting, not worth overstating as a mapped construct. It's also
  worth noting DART's own results found data sovereignty conflict operated
  as a boundary condition rather than a direct predictor in their model,
  which is a separate, empirical reason not to lean on it here.

## The visibility/implementation gap

A recurring theme across this literature -- DART's abstract states its
survey results "reveal persistent gaps in employee awareness, training,
and organizational controls surrounding AI use," and Silic, Silic, and
Kind-Trüller's mixed-methods study of Shadow AI (Silic, M., Silic, D., &
Kind-Trüller, K. (2025). From Shadow IT to Shadow AI: Threats, risks and
opportunities for organizations. *Strategic Change*. Based on 140 survey
responses and 10 executive interviews, examining how employees perceive
and justify Shadow AI use and how organizational structures fail to
regulate it) documents organizational structures failing to regulate
Shadow AI's spread -- is that organizations cannot govern AI tool use they
cannot see, and cannot see it without some discovery mechanism in place
first. That ordering (visibility before governance) is the reason SHADE's
own stage order is Discover before Govern rather than the reverse, and it
is the specific, narrow claim this document makes about a "gap": not a
named framework, just the observed sequencing dependency that both cited
studies' findings are consistent with.
