#!/usr/bin/env python3
"""
experiments/benchmark_dataset_generator.py

Scaffold for a future, standalone dataset-paper candidate: a larger, more
STRUCTURALLY diverse synthetic Shadow AI usage dataset than
shade/generate_synthetic_data.py produces. 100% Faker-generated; no real
organizational, employee, or customer data is used or referenced anywhere
in this script or its output, consistent with the rest of this repository.

WHAT "STRUCTURAL DIVERSITY" MEANS HERE, CONCRETELY (this is the part
shade/generate_synthetic_data.py doesn't attempt, by design -- that script
produces one consistent record shape sized for the core pipeline demo):

  1. Multiple organizational SCENARIO PROFILES (startup / enterprise /
     regulated-industry), each with its own tool-risk mix, department
     mix, and PII-injection rate -- so the dataset varies across simulated
     organizational contexts, not just record count.
  2. SESSION structure: events are grouped into synthetic conversational
     sessions (a session_id shared by 1-5 events), a first step toward
     longitudinal/session-level analysis this repo's core pipeline does
     not currently attempt (see docs/theory.md's note that SHADE processes
     point-in-time events with no behavioral/temporal model -- this
     generator is a step toward being ABLE to study that, not a claim
     that SHADE already does).
  3. Multiple structurally distinct PROMPT TEMPLATES (code assistance,
     document drafting, customer-record lookup, meeting-notes
     summarization), each with its own realistic-but-synthetic
     PII-injection pattern, rather than one generic paragraph shape.
  4. Multiple Faker LOCALES for name/text generation, so the dataset isn't
     uniformly US-English-shaped -- still entirely synthetic, just more
     structurally varied.

STATUS: standalone scaffold, NOT wired into shade/run_pipeline.py or the core
test suite. Wiring a new dataset generator into the reference pipeline
would change shade/run_pipeline.py's documented output shape and the numbers in
README/docs/benchmark.md; that's out of scope for this scaffold and would
need its own review pass first. This module is meant to be run and
inspected on its own, as the starting point for a future, separate
dataset-paper contribution.

Usage:
    python experiments/benchmark_dataset_generator.py --n 5000 --out experiments/output/benchmark_dataset.csv
"""
import argparse
import csv
import json
import os
import random
import secrets
import sys
from datetime import datetime, timedelta

try:
    from faker import Faker
except ImportError:
    raise SystemExit("Faker is required: pip install -r requirements.txt")

# Allow running this script directly (adds repo root to path so it can
# reuse the real tool registry rather than duplicating it).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yaml

DEFAULT_REGISTRY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "known_endpoints.yaml")

# Each profile is an author-defined SIMULATION SCENARIO, not a measured or
# cited real-world statistic. Weights are chosen to produce structurally
# distinct datasets per profile, nothing more.
SCENARIO_PROFILES = {
    "startup": {
        "unsanctioned_prob": 0.80,   # small orgs, little governance tooling in place
        "departments": ["Engineering", "Product", "Growth", "Ops"],
        "sensitivity_weights": {"public": 0.60, "sensitive": 0.30, "critical": 0.10},
        "locale": "en_US",
        "session_size_range": (1, 3),
    },
    "enterprise": {
        "unsanctioned_prob": 0.45,   # more sanctioned tooling available
        "departments": ["Engineering", "Finance", "HR", "Legal", "Marketing",
                         "Customer Support", "Product", "Data Science", "Operations"],
        "sensitivity_weights": {"public": 0.50, "sensitive": 0.32, "critical": 0.18},
        "locale": "en_GB",
        "session_size_range": (1, 5),
    },
    "regulated_industry": {
        "unsanctioned_prob": 0.30,   # stricter baseline policy, still nonzero shadow usage
        "departments": ["Compliance", "Legal", "Clinical Operations", "Finance", "Engineering"],
        "sensitivity_weights": {"public": 0.35, "sensitive": 0.35, "critical": 0.30},
        "locale": "de_DE",
        "session_size_range": (1, 4),
    },
}

PROMPT_TEMPLATES = ["code_assistance", "document_drafting", "customer_record_lookup", "meeting_notes"]


def fake_secret_token():
    return "sk-fake-" + secrets.token_urlsafe(24)


def build_prompt(fake, template, sensitivity):
    """
    Structurally distinct prompt shapes per template, with injection rate
    and content still keyed to the sensitivity label (same ground-truth
    principle as shade/generate_synthetic_data.py: shade/dlp_redact.py has a real
    pattern to find when sensitivity implies one should be there).
    """
    injected = []
    if sensitivity == "critical":
        injected.append(fake_secret_token())
        injected.append(f"contact: {fake.email()}")
        if random.random() < 0.4:
            injected.append(f"ssn: {fake.ssn()}")
    elif sensitivity == "sensitive":
        injected.append(f"contact: {fake.email()}")
        if random.random() < 0.3:
            injected.append(f"phone: {fake.phone_number()}")

    if template == "code_assistance":
        body = f"Can you review this function and suggest improvements: def process(x): return x * {random.randint(2,9)}"
    elif template == "document_drafting":
        body = fake.paragraph(nb_sentences=3)
    elif template == "customer_record_lookup":
        body = f"Look up the record for {fake.name()} and summarize their recent activity."
    else:  # meeting_notes
        body = f"Summarize these meeting notes: {fake.paragraph(nb_sentences=2)}"

    return body + " " + " ".join(injected)


def load_tool_population(registry_path):
    with open(registry_path) as f:
        registry = yaml.safe_load(f)
    sanctioned = [(t["name"], "sanctioned", t["tool_risk"]) for t in registry["sanctioned"]]
    unsanctioned = [(t["name"], "unsanctioned", t["tool_risk"]) for t in registry["unsanctioned"]]
    return sanctioned, unsanctioned


def generate(n, registry_path=DEFAULT_REGISTRY, seed=42):
    random.seed(seed)
    sanctioned, unsanctioned = load_tool_population(registry_path)
    now = datetime.utcnow()

    rows = []
    event_i = 0
    profile_names = list(SCENARIO_PROFILES.keys())

    while event_i < n:
        profile_name = random.choice(profile_names)
        profile = SCENARIO_PROFILES[profile_name]
        fake = Faker(profile["locale"])
        Faker.seed(seed + event_i)  # vary per-session but stay reproducible for a fixed seed

        session_id = f"SESS-{profile_name[:3].upper()}-{event_i:07d}"
        session_size = random.randint(*profile["session_size_range"])
        employee_id = f"EMP-{profile_name[:3].upper()}-{event_i:06d}"
        department = random.choice(profile["departments"])
        role = fake.job()

        for _ in range(session_size):
            if event_i >= n:
                break
            if random.random() < profile["unsanctioned_prob"]:
                tool_name, tool_class, tool_risk = random.choice(unsanctioned)
            else:
                tool_name, tool_class, tool_risk = random.choice(sanctioned)

            weights = profile["sensitivity_weights"]
            sensitivity = random.choices(list(weights.keys()), weights=list(weights.values()), k=1)[0]
            template = random.choice(PROMPT_TEMPLATES)
            ts = now - timedelta(days=random.randint(0, 90), hours=random.randint(0, 23), minutes=random.randint(0, 59))

            rows.append({
                "event_id": f"EVT-{event_i:07d}",
                "session_id": session_id,
                "scenario_profile": profile_name,
                "timestamp": ts.isoformat(),
                "employee_id": employee_id,
                "department": department,
                "role": role,
                "locale": profile["locale"],
                "tool_name": tool_name,
                "tool_class": tool_class,
                "tool_risk": tool_risk,
                "data_sensitivity": sensitivity,
                "prompt_template": template,
                "prompt_text": build_prompt(fake, template, sensitivity),
            })
            event_i += 1

    return rows


def summarize(rows):
    from collections import Counter
    return {
        "total_events": len(rows),
        "sessions": len(set(r["session_id"] for r in rows)),
        "by_scenario_profile": dict(Counter(r["scenario_profile"] for r in rows)),
        "by_prompt_template": dict(Counter(r["prompt_template"] for r in rows)),
        "by_locale": dict(Counter(r["locale"] for r in rows)),
        "by_tool_class": dict(Counter(r["tool_class"] for r in rows)),
        "note": (
            "100% Faker-generated synthetic data across three author-defined "
            "scenario profiles (startup/enterprise/regulated_industry). No "
            "real organizational, employee, or customer data. Scenario "
            "weights are simulation parameters, not measured real-world "
            "statistics. Standalone scaffold, not wired into shade/run_pipeline.py."
        ),
    }


def main():
    ap = argparse.ArgumentParser(description="Generate a larger, structurally diverse synthetic benchmark dataset (scaffold, not part of the core pipeline).")
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--out", type=str, default="experiments/output/benchmark_dataset.csv")
    ap.add_argument("--summary_out", type=str, default="experiments/output/benchmark_dataset_summary.json")
    ap.add_argument("--registry", type=str, default=DEFAULT_REGISTRY)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rows = generate(args.n, args.registry, seed=args.seed)
    report = summarize(rows)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    with open(args.summary_out, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Generated {len(rows)} synthetic events across {report['sessions']} sessions -> {args.out}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
