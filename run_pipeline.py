#!/usr/bin/env python3
"""
run_pipeline.py
Orchestrator for Project SHADE (paper Section 8, Phases 1-6). Runs
generation -> discovery -> DLP -> governance decisioning -> dashboard ->
internal-checks report, entirely locally, using only synthetic data.

Calls each phase's functions directly in-process (no subprocess spawning) --
every phase script is independently runnable via its own CLI too, this
orchestrator just reuses the same functions rather than re-invoking them
as separate processes.

Usage:
    python run_pipeline.py --n 2000
"""
import argparse
import csv
import json
import os

import generate_synthetic_data as gen
import discovery_scan as discovery
import dlp_redact as dlp
import governance_score as gov
import build_dashboard as dash


def write_csv(rows, path):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description="Run the full Shadow AI governance prototype pipeline.")
    ap.add_argument("--n", type=int, default=2000, help="Number of synthetic events to generate.")
    args = ap.parse_args()

    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs("output", exist_ok=True)

    # Phase 1: generate
    events = gen.generate(args.n, "config/known_endpoints.yaml")
    write_csv(events, "output/synthetic_usage.csv")
    print(f"[1/5] Generated {len(events)} synthetic events -> output/synthetic_usage.csv")

    # Phase 2: discovery
    discovery_report = discovery.run_discovery(events)
    with open("output/discovery_report.json", "w") as f:
        json.dump(discovery_report, f, indent=2)
    print(f"[2/5] Discovery: {discovery_report['unsanctioned_event_pct']}% unsanctioned -> output/discovery_report.json")

    # Phase 3: DLP
    dlp_report = dlp.redact_events(events)
    write_csv(events, "output/redacted_events.csv")
    with open("output/redaction_report.json", "w") as f:
        json.dump(dlp_report, f, indent=2)
    print(f"[3/5] DLP: triggered on {dlp_report['redaction_trigger_rate_pct']}% of events -> output/redaction_report.json")

    # Phase 4: governance scoring
    gov_report = gov.score_events(events)
    write_csv(events, "output/scored_events.csv")
    with open("output/governance_report.json", "w") as f:
        json.dump(gov_report, f, indent=2)
    print(f"[4/5] Governance: {gov_report['action_distribution_pct']} -> output/governance_report.json")

    # Phase 5: dashboard
    fig_path = "output/dashboard.png"
    dash.render(discovery_report, dlp_report, gov_report, fig_path)
    print(f"[5/5] Dashboard -> {fig_path}")

    # Phase 6: internal-checks report (filename retained as VALIDATION_REPORT.md
    # for output-contract stability; title/body describe internal checks and
    # stated limitations rather than independent validation)
    validation = f"""# Internal Checks and Limitations — Shadow AI Governance Prototype
(Synthetic data only. See paper Section 8.6-8.7 for scope and limitations.)

Generated events: {args.n}

## Discovery layer
- Unsanctioned events detected: {discovery_report['unsanctioned_event_count']} / {discovery_report['total_events_scanned']} ({discovery_report['unsanctioned_event_pct']}%)
- tool_class is ground-truth-labeled at generation time, so discovery precision/recall = 100%
  by construction in this offline demo. This is not an independent measurement of discovery
  accuracy: the generator creates tool_class and the discovery module reads that same field.
  Real deployments have no equivalent built-in ground truth and require validation through
  periodic manual audit samples instead (see paper Section 3.5, Section 8.6).

## DLP layer
- Sensitive-pattern trigger rate: {dlp_report['redaction_trigger_rate_pct']}% of events
- Hits by pattern type: {json.dumps(dlp_report['hits_by_pattern_type'])}
- These are outputs of this one synthetic reference run against four configured regex
  expressions, not an estimate of DLP precision, recall, F1, or general effectiveness
  (see paper Section 5.2 / 8.6). A separate, dedicated benchmark (`eval_harness.py`,
  see docs/benchmark.md) DOES report precision/recall/F1 against a purpose-built
  synthetic ground-truth set -- but that is still internal consistency against
  synthetic ground truth, not a real-world accuracy estimate. Production deployments
  could add Presidio/spaCy ML entity recognition; any recall improvement should be
  measured against independently annotated data, not assumed.

## Governance layer
- Action distribution: {json.dumps(gov_report['action_distribution'])}
- Blocked or override-required: {gov_report['blocked_or_override_pct']}% of events
- This shows the implemented table returns the expected action for each generated
  combination; it does not establish that the matrix is calibrated for any particular
  organization, legal regime, or threat environment. The matrix's completeness and
  non-conflict ARE formally verified (see verify_policy.py and
  docs/adr/0001-formal-verification-of-governance-matrix.md) -- that verifies the
  table is well-formed, not that its policy choices are the right ones for any
  given context.

## Explicit limitations (paper Section 8.6)
This prototype does not demonstrate TLS interception at scale, eBPF kernel-level tracing,
real adversarial evasion, repeated-user/longitudinal profile analysis, or performance at
enterprise data volume. See paper Sections 3, 5, and 6 for the production-grade open-source
tools (AIOStack, aidlp, Zeek/Suricata, ELK/OpenSearch) this prototype's logic is modeled on
but does not replace.

## Ethical disclosure
100% synthetic data (Faker-generated). No real organizational, employee, or customer data
was used at any stage.
"""
    with open("output/VALIDATION_REPORT.md", "w") as f:
        f.write(validation)

    print("\n=== Pipeline complete ===")
    print("Outputs (in output/): synthetic_usage.csv, discovery_report.json, redacted_events.csv,")
    print("redaction_report.json, scored_events.csv, governance_report.json,")
    print("dashboard.png, VALIDATION_REPORT.md")


if __name__ == "__main__":
    main()
