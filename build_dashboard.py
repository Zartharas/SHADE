#!/usr/bin/env python3
"""
build_dashboard.py
Phase 5 of Project SHADE, see paper Section 8.5 / 6.

Lightweight, local, matplotlib-based stand-in for the production ELK/
OpenSearch monitoring dashboard described in paper Section 6. Reads the
JSON reports produced by discovery_scan.py, dlp_redact.py, and
governance_score.py and renders summary visualizations to a single PNG.
(The plain-text internal-checks summary, VALIDATION_REPORT.md, is written
by run_pipeline.py, not by this script.)

Usage:
    python build_dashboard.py --discovery output/discovery_report.json \
        --dlp output/redaction_report.json --governance output/governance_report.json \
        --out output/dashboard.png
"""
import argparse
import json
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load(path):
    with open(path) as f:
        return json.load(f)


def render(discovery, dlp, governance, out_path):
    """Render the four-panel dashboard from already-loaded report dicts.
    Shared by both the CLI (main, below) and run_pipeline.py's in-process call."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    fig.suptitle("Shadow AI Governance Prototype: Monitoring Dashboard (Synthetic Data)", fontsize=13)

    # Panel 1: Sanctioned vs Unsanctioned event volume
    ax = axes[0][0]
    labels = ["Unsanctioned", "Sanctioned"]
    values = [discovery["unsanctioned_event_count"], discovery["sanctioned_event_count"]]
    ax.bar(labels, values, color=["#c0392b", "#27ae60"])
    ax.set_title(f"Discovery: Tool Class Split\n({discovery['unsanctioned_event_pct']}% unsanctioned)")
    ax.set_ylabel("Event count")

    # Panel 2: Top tools by usage
    ax = axes[0][1]
    top_tools = list(discovery["events_by_tool"].items())[:6]
    names = [t[0] for t in top_tools]
    counts = [t[1] for t in top_tools]
    ax.barh(names, counts, color="#2980b9")
    ax.set_title("Top AI Tools by Event Volume")
    ax.invert_yaxis()

    # Panel 3: DLP redaction trigger rate
    ax = axes[1][0]
    hits = dlp.get("hits_by_pattern_type", {})
    if hits:
        ax.pie(hits.values(), labels=hits.keys(), autopct="%1.0f%%")
    ax.set_title(f"DLP: Sensitive Pattern Hits by Type\n(triggered on {dlp['redaction_trigger_rate_pct']}% of events)")

    # Panel 4: Governance action distribution
    ax = axes[1][1]
    dist = governance["action_distribution"]
    ax.bar(dist.keys(), dist.values(), color="#8e44ad")
    ax.set_title("Governance: Decision Matrix Outcomes")
    ax.tick_params(axis="x", rotation=30, labelsize=8)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    plt.savefig(out_path, dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description="Render Shadow AI governance monitoring dashboard.")
    ap.add_argument("--discovery", default="output/discovery_report.json")
    ap.add_argument("--dlp", default="output/redaction_report.json")
    ap.add_argument("--governance", default="output/governance_report.json")
    ap.add_argument("--out", default="output/dashboard.png")
    args = ap.parse_args()

    render(load(args.discovery), load(args.dlp), load(args.governance), args.out)
    print(f"Dashboard written to {args.out}")


if __name__ == "__main__":
    main()
