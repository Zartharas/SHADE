#!/usr/bin/env python3
"""
shade/discovery_scan.py
Phase 2 of Project SHADE, see paper Section 8.2.

IMPORTANT: this module does NOT perform independent AI-destination
identification or compare live telemetry against config/known_endpoints.yaml.
It reads the tool_class value already assigned by generate_synthetic_data.py
and aggregates/summarizes it. It therefore demonstrates downstream handling
of an existing classification, not the detection step itself.

In PRODUCTION, actual detection is what Zeek/Suricata perform against
TLS SNI/JA3 fingerprints on the wire, and what AIOStack performs via eBPF
kernel tracepoints inside Kubernetes -- see paper Section 3.1. Those tools
would have to infer tool identity from observed technical evidence rather
than read a label embedded in the event, which is what this module does.
This script operates on the CSV produced by generate_synthetic_data.py,
not on live network traffic, and makes no network calls of its own.

Usage:
    python3 shade/discovery_scan.py --in output/synthetic_usage.csv --out output/discovery_report.json
"""
import argparse
import json
import csv
import os
from collections import defaultdict


def load_events(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def run_discovery(events):
    """
    Classifies each event as sanctioned/unsanctioned using the ground-truth
    tool_class field written by generate_synthetic_data.py -- standing in for
    what a real discovery tool would derive from a maintained endpoint registry
    (see config/known_endpoints.yaml) rather than from a label baked into the event.
    """
    total = len(events)
    unsanctioned_events = [e for e in events if e["tool_class"] == "unsanctioned"]
    sanctioned_events = [e for e in events if e["tool_class"] == "sanctioned"]

    by_tool = defaultdict(int)
    by_department = defaultdict(lambda: {"sanctioned": 0, "unsanctioned": 0})
    by_employee_unsanctioned = defaultdict(int)

    for e in events:
        by_tool[e["tool_name"]] += 1
        by_department[e["department"]][e["tool_class"]] += 1
        if e["tool_class"] == "unsanctioned":
            by_employee_unsanctioned[e["employee_id"]] += 1

    # NOTE: employee_id is unique per event (see generate_synthetic_data.py),
    # so this cannot currently represent repeated behavior by the same
    # person and is not an implementation of the Section 4.3 power-user
    # profile -- it only ranks single-event employee IDs.
    power_users = sorted(
        by_employee_unsanctioned.items(), key=lambda kv: kv[1], reverse=True
    )[:10]

    report = {
        "total_events_scanned": total,
        "unsanctioned_event_count": len(unsanctioned_events),
        "unsanctioned_event_pct": round(100 * len(unsanctioned_events) / total, 1) if total else 0,
        "sanctioned_event_count": len(sanctioned_events),
        "events_by_tool": dict(sorted(by_tool.items(), key=lambda kv: kv[1], reverse=True)),
        "department_breakdown": {
            dept: v for dept, v in sorted(
                by_department.items(),
                key=lambda kv: kv[1]["unsanctioned"],
                reverse=True,
            )
        },
        "top_unsanctioned_power_users": power_users,
    }
    return report


def main():
    ap = argparse.ArgumentParser(description="Discovery layer: classify sanctioned vs unsanctioned AI usage.")
    ap.add_argument("--in", dest="infile", type=str, default="output/synthetic_usage.csv")
    ap.add_argument("--out", type=str, default="output/discovery_report.json")
    args = ap.parse_args()

    events = load_events(args.infile)
    report = run_discovery(events)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Discovery scan complete: {report['unsanctioned_event_count']}/{report['total_events_scanned']} "
          f"events ({report['unsanctioned_event_pct']}%) routed through unsanctioned tools.")
    print(f"Report written to {args.out}")


if __name__ == "__main__":
    main()
