# Project SHADE

**Scan, Hunt, Assess, Decide, Enforce**

*"Mastering the shadows"*

[![SHADE self-check](https://github.com/Zartharas/SHADE/actions/workflows/test.yml/badge.svg)](https://github.com/Zartharas/SHADE/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](requirements.txt)
[![Zero-budget](https://img.shields.io/badge/dependencies-zero--budget-brightgreen.svg)](#quick-start)

SHADE is an offline prototype for the Shadow AI governance framework
developed in the companion paper, *"Governing Unseen Knowledge: A Practical
Framework for Discovering, Classifying, and Managing Shadow AI as an
Organizational Knowledge Risk"* (paper Section 8).

This is a local, offline, dependency-light demonstration of the
Discover → Classify → Govern → Validate framework described in the paper.
It runs entirely on synthetic data generated with [Faker](https://github.com/joke2k/faker)
and makes no network calls, no cloud dependencies, and uses no real
organizational, employee, or customer data at any stage.

**At a glance:** 100% synthetic (Faker-generated) data &nbsp;·&nbsp; zero
network calls &nbsp;·&nbsp; governance decision matrix formally verified
by exhaustive enumeration ([ADR 0001](docs/adr/0001-formal-verification-of-governance-matrix.md))
&nbsp;·&nbsp; three optional extensions, each opt-in and off by default
([ADR 0002](docs/adr/0002-integrating-llm-policy-proposer.md)-[0004](docs/adr/0004-integrating-dp-aggregate-reporting.md))
&nbsp;·&nbsp; MIT licensed

**Contents:** [What this is, and isn't](#what-this-is-and-isnt) ·
[Layout](#layout) · [Quick start](#quick-start) ·
[Reproducing at scale](#reproducing-at-scale) ·
[Production tooling](#production-tooling-real-deployments) ·
[Legal and ethical notes](#legal-and-ethical-notes) ·
[License](#license) · [Citing this work](#citing-this-work)

<p align="center">
  <img src="docs/pipeline_animation.svg" alt="Animated diagram of the SHADE pipeline: Generate, Discover, Classify, Govern, Validate, each stage highlighting in sequence as a run passes through it" width="820">
</p>

<p align="center"><sub>Self-contained animated SVG (no JS, loops automatically) -- if it renders as static in your viewer, the Mermaid diagram below is the same flow as a text-based fallback.</sub></p>

```mermaid
flowchart LR
    A[shade/generate_synthetic_data.py<br/><sub>Faker, 100% synthetic</sub>] --> B[shade/discovery_scan.py<br/><sub>Discover: sanctioned split</sub>]
    B --> C[shade/dlp_redact.py<br/><sub>Classify: DLP + risk tier</sub>]
    C --> D[shade/governance_score.py<br/><sub>Govern: verified decision matrix</sub>]
    D --> E[shade/build_dashboard.py<br/><sub>Validate: harness + report</sub>]
    F[shade/verify_policy.py<br/><sub>formal verification gate</sub>] -.guards.-> D
    G[shade/eval_harness.py<br/><sub>DLP precision/recall/F1</sub>] -.checks.-> C
```

<p align="center">
  <img src="docs/example_dashboard.png" alt="SHADE monitoring dashboard: discovery tool-class split, top AI tools by event volume, DLP sensitive-pattern hits by type, and governance decision-matrix outcomes, all on synthetic data" width="820">
</p>

<p align="center"><sub>Output of <code>python3 shade/run_pipeline.py --n 2000</code> against the reference synthetic dataset (fixed seed). Regenerate anytime — see Quick start below.</sub></p>

## What this is, and isn't

SHADE demonstrates the framework's execution path and checks selected
internal rules; it does not validate production-scale performance or
accuracy against real-world data. It is not a substitute for the real,
production-grade open-source tools cited throughout the paper. Do not
deploy this code as-is against real traffic or real employee data: see
"Production tooling" below.

The software itself can be run without purchasing a commercial license or
paid cloud resource ("zero-budget" in that narrow sense), but local compute,
storage, maintenance, and development time still carry real operational cost.

| SHADE module | Relationship to production tooling | Paper section |
|---|---|---|
| `shade/generate_synthetic_data.py` | N/A: synthetic data generation only | 8.1 |
| `shade/discovery_scan.py` | Reads a generated ground-truth label; does not perform independent detection like Zeek / Suricata (SNI/JA3), AIOStack (eBPF), or agent-discover-scanner | 3, 8.2 |
| `shade/dlp_redact.py` | Regex-only; illustrates the pattern used by aidlp / llmproxy (mitmproxy + Presidio/spaCy) without their ML-based recognition | 5.2, 8.3 |
| `shade/governance_score.py` | Deterministic rule-table lookup, not a stand-in for ML-judge governance tools such as GovLLM or IBM AI Atlas Nexus | 4.4, 8.4 |
| `shade/build_dashboard.py` | Static local visualization; not a substitute for ELK / OpenSearch | 6, 8.5 |
| `shade/policy_proposer.py` | Mock-backend policy-change proposer, gated by formal verification, opt-in pipeline stage; not a stand-in for an evaluated LLM-based governance tool -- see docs/extensions.md | new, see docs/adr/0002 |
| `shade/mcp_tool_call_monitor.py` | Synthetic agent tool-call (MCP) telemetry and a second, independently-verified governance table; not a stand-in for real MCP server instrumentation -- see docs/extensions.md | new, see docs/adr/0003 |
| `shade/dp_aggregate_reporting.py` | Laplace-mechanism differential privacy on aggregate reporting outputs; no privacy budget composition across releases -- see docs/extensions.md | new, see docs/adr/0004 |

## Layout

```
shade/        the core package: five pipeline phases + orchestrator (run_pipeline.py)
              + verification (verify_policy.py) + eval harness (eval_harness.py)
              + policy_proposer.py (opt-in pipeline stage, see docs/adr/0002)
              + mcp_tool_call_monitor.py (opt-in pipeline stage, see docs/adr/0003)
              + dp_aggregate_reporting.py (opt-in pipeline stage, see docs/adr/0004)
tests/        test_pipeline.py -- the self-check suite (20 checks)
config/       tool registry (known_endpoints.yaml)
docs/         theory.md, benchmark.md, extensions.md, shadow-ai-vs-shadow-it.md, adr/, example dashboard image
experiments/  eval harness configs + benchmark dataset generator scaffold; experiments/output/ is generated+gitignored
extensions/   empty as of ADR 0004 (all three original prototypes graduated into shade/); starting point for future standalone additions, see docs/extensions.md
scripts/      run_extended_benchmark.py -- opt-in, slower scale/multi-seed check, see "Reproducing at scale" below
output/       generated pipeline artifacts (gitignored; regenerate anytime)
paper/        manuscript/submission drafts (gitignored, local-only)
```

Every script under `shade/` and `tests/` is runnable two equivalent ways
from the repo root: directly by path (`python3 shade/run_pipeline.py`) or
as a module (`python3 -m shade.run_pipeline`) -- both resolve imports and
relative paths (`config/`, `output/`) the same way. `extensions/` and
`experiments/` scripts support direct-path execution only (they're
standalone by design, not part of the `shade` package).

- `docs/theory.md` maps SHADE's four stages against NIST AI RMF, ISO/IEC
  42001, and DART's constructs -- including where a mapping is genuine and
  where it isn't.
- `docs/benchmark.md` states exactly what the evaluation harness measures
  and what it doesn't (internal consistency against synthetic ground
  truth, not real-world accuracy).
- `docs/extensions.md` records the history of the three prototypes that
  started in `extensions/` and later graduated into `shade/` (ADR
  0002-0004): what each demonstrated standalone and, as importantly,
  what integration did and didn't change about those claims.
- `docs/shadow-ai-vs-shadow-it.md` is a short comparative note grounded in
  DART and Silic et al. (2025), distinguishing Shadow AI from the older
  Shadow IT category this project's discovery/inventory approach descends
  from.
- `docs/adr/` records the reasoning behind non-obvious design decisions,
  starting with why the governance matrix is verified by exhaustive
  enumeration rather than a SAT/SMT solver.
- `CONTRIBUTING.md` covers the project's hard constraints (synthetic data
  only, offline only, anonymity during review) for anyone touching this
  code, including future changes by the maintainer.

## Quick start

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt        # pinned exact versions; or: pip install -r requirements.txt --break-system-packages
python3 shade/run_pipeline.py --n 2000
```

Or, for an exactly reproducible reference environment:

```bash
docker build -t shade .
docker run --rm -v "$(pwd)/output:/app/output" shade python3 shade/run_pipeline.py --n 2000
```

This produces, in `output/`:

- `synthetic_usage.csv`: the raw synthetic dataset
- `discovery_report.json`: sanctioned/unsanctioned split, top tools, department breakdown
- `redacted_events.csv`, `redaction_report.json`: DLP redaction results
- `scored_events.csv`, `governance_report.json`: governance decision-matrix outcomes
- `dashboard.png`: four-panel visual summary
- `VALIDATION_REPORT.md`: Phase 6 internal-checks summary and explicit limitations (filename retained from earlier drafts; the report documents internal checks and stated limitations, not independent validation)

Each script is also runnable independently: run `python3 shade/<script>.py --help`
for options (or `python3 -m shade.<script> --help`, see "Layout" above). `shade/run_pipeline.py` calls each phase's functions directly
in-process rather than shelling out, so there's exactly one implementation
of the discovery/DLP/governance/dashboard logic, shared by the CLI and the
orchestrator.

Run the self-check (formally verifies the governance decision matrix,
checks DLP redaction patterns and their statistical confidence intervals,
runs the DLP evaluation harness against its precision/recall/F1
thresholds, exercises the policy proposer's verify/guardrail behavior,
exercises the MCP tool-call monitor's second governance table and
generator, and exercises the DP aggregate reporter's Laplace mechanism
and privacy/utility trade-off -- see docs/benchmark.md,
docs/adr/0002-integrating-llm-policy-proposer.md,
docs/adr/0003-integrating-mcp-tool-call-monitor.md, and
docs/adr/0004-integrating-dp-aggregate-reporting.md) with:

```bash
python3 tests/test_pipeline.py
```

The formal verification and evaluation harness can also be run standalone:

```bash
python3 shade/verify_policy.py                                   # governance matrix: completeness + non-conflict
python3 shade/eval_harness.py --n 300 --seed 42                  # DLP: precision/recall/F1 + 95% CIs vs. synthetic ground truth
python3 shade/eval_harness.py --tier hard                        # DLP: diagnostic hard tier (OCR noise, homoglyphs, obfuscation, intl formats) -- see docs/benchmark.md
```

### Reproducing at scale

`tests/test_pipeline.py` above is fast (n=300 DLP benchmark) by design, so
it can run on every push. To check whether that result holds at higher
volume and across more seeds, and to stress-test the three opt-in
pipeline extensions (ADR 0002-0004) under load, run:

```bash
python3 scripts/run_extended_benchmark.py
```

or, for an environment-independent run via Docker:

```bash
docker build -t shade .
docker run --rm -v "$(pwd)/experiments/output:/app/experiments/output" shade python3 scripts/run_extended_benchmark.py
```

This is also wired into CI as a manually-triggered job (`extended-benchmark`
in `.github/workflows/test.yml`) -- anyone with a fork can run it from the
Actions tab ("SHADE self-check" -> "Run workflow") and download the
resulting JSON report as a build artifact, no local setup required. See
`docs/benchmark.md`'s "Scale check" section for the numbers this last
produced and why this check is kept separate from the fast, always-on
`tests/test_pipeline.py` gate.

## Production tooling (real deployments)

For an actual organizational rollout, replace each SHADE module with the
verified open-source tools cited in the paper:

| Category | Tools |
|---|---|
| **Discovery** | [AIOStack](https://github.com/aurva-io/AIOstack) (Kubernetes/eBPF), [agent-discover-scanner](https://github.com/Defend-AI-Tech-Inc/agent-discover-scanner), [AI-Detector](https://github.com/shamo0/AI-Detector) (MDM/endpoint), [Zeek](https://zeek.org) / [Suricata](https://suricata.io) (network SNI/JA3) |
| **DLP** | [aidlp](https://github.com/fabriziosalmi/aidlp), [llmproxy](https://github.com/fabriziosalmi/llmproxy), [Microsoft Presidio](https://github.com/microsoft/presidio), [OpenDLP](https://github.com/ezarko/opendlp), [MyDLP](https://github.com/mydlp/mydlp) |
| **Secrets hygiene** | [trufflehog](https://github.com/trufflesecurity/trufflehog), [gitleaks](https://github.com/gitleaks/gitleaks) |
| **Governance** | [GovLLM](https://github.com/JehanneDussert/govllm), [IBM ai-atlas-nexus](https://github.com/IBM/ai-atlas-nexus) |
| **Monitoring** | [Elastic (ELK) Stack](https://elastic.co), [OpenSearch](https://opensearch.org) |

## Legal and ethical notes

- All data is synthetic. Do not point `shade/generate_synthetic_data.py`'s output
  format at a real data-export pipeline without a full legal/privacy review.
- Deploying TLS-interception (mitmproxy-based) DLP in production requires
  jurisdiction-specific legal review and, in some jurisdictions, works-council
  consultation before enabling content-level inspection. See paper Section 5.4.
- This code is provided for educational/demonstration purposes only.

## License

MIT, see [LICENSE](LICENSE).

## Citing this work

If you use this code or the accompanying paper, see [CITATION.cff](CITATION.cff).
Author identity is currently redacted pending the outcome of double-anonymous
peer review (see the note at the bottom of that file); full attribution will
be restored once a review decision is issued. GitHub renders a
"Cite this repository" button automatically from this file.
