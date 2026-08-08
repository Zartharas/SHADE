#!/usr/bin/env python3
"""
generate_synthetic_data.py
Phase 1 of Project SHADE (Shadow Hunt, Assess, Decide, Enforce), see paper Section 8.1.

Generates a fully SYNTHETIC dataset of employee AI-tool-usage events using
the Faker library. No real organizational, employee, or customer data is
used or referenced anywhere in this script or its output.

Each record simulates:
  - a synthetic employee (id, department, role)
  - an AI tool used (drawn from config/known_endpoints.yaml's sanctioned +
    unsanctioned population; the 0.67 unsanctioned-selection probability
    below is an author-selected scenario parameter used to produce a
    dataset with substantial unsanctioned activity, not a measured or
    cited prevalence rate)
  - a data-sensitivity label for the (synthetic) content shared
  - a synthetic "prompt" field seeded with FAKE PII/secret-shaped strings
    for the DLP layer (dlp_redact.py) to detect and redact
  - a timestamp

Usage:
    python generate_synthetic_data.py --n 2000 --out output/synthetic_usage.csv
"""
import argparse
import os
import random
import secrets
import csv
import yaml
from datetime import datetime, timedelta

try:
    from faker import Faker
except ImportError:
    raise SystemExit(
        "Faker is required. Install with: pip install -r requirements.txt "
        "(or: pip install faker --break-system-packages)"
    )

DEPARTMENTS = [
    "Engineering", "Finance", "HR", "Legal", "Marketing",
    "Customer Support", "Product", "Data Science", "Operations",
]

DATA_SENSITIVITY = ["public", "sensitive", "critical"]
# Author-selected scenario weights: "critical" events are a meaningful
# minority rather than the majority, so the generated dataset has a
# plausible mix of severity levels to exercise the decision matrix.
# These are simulation parameters, not measured or cited real-world figures.
SENSITIVITY_WEIGHTS = [0.55, 0.30, 0.15]


def load_tool_population(registry_path):
    with open(registry_path, "r") as f:
        registry = yaml.safe_load(f)
    sanctioned = [(t["name"], "sanctioned", t["tool_risk"]) for t in registry["sanctioned"]]
    unsanctioned = [(t["name"], "unsanctioned", t["tool_risk"]) for t in registry["unsanctioned"]]
    return sanctioned, unsanctioned


def fake_secret_token():
    """FAKE API-key-shaped string via stdlib secrets. Never a real key."""
    return "sk-fake-" + secrets.token_urlsafe(24)


def build_prompt_text(fake, sensitivity):
    """
    Build a synthetic 'prompt' the employee supposedly sent to the AI tool.
    Injects fake PII/secret patterns at a rate correlated with the declared
    sensitivity label, so dlp_redact.py has known ground truth to validate against.
    """
    base = fake.paragraph(nb_sentences=2)
    injected = []
    if sensitivity == "critical":
        # Injects a fake credential/PII pattern for the DLP layer to detect.
        injected.append(fake_secret_token())
        injected.append(f"contact: {fake.email()}")
        if random.random() < 0.4:
            injected.append(f"ssn: {fake.ssn()}")
    elif sensitivity == "sensitive":
        injected.append(f"contact: {fake.email()}")
        if random.random() < 0.3:
            injected.append(f"phone: {fake.phone_number()}")
    # public: no injected sensitive patterns
    return base + " " + " ".join(injected)


def generate(n, registry_path, seed=42):
    random.seed(seed)
    fake = Faker()
    Faker.seed(seed)

    sanctioned, unsanctioned = load_tool_population(registry_path)

    now = datetime.utcnow()
    rows = []
    for i in range(n):
        # Author-selected scenario parameter: routes ~67% of events through
        # unsanctioned tools to produce a dataset with substantial
        # unsanctioned activity. Not a measured or cited prevalence rate.
        if random.random() < 0.67:
            tool_name, tool_class, tool_risk = random.choice(unsanctioned)
        else:
            tool_name, tool_class, tool_risk = random.choice(sanctioned)

        sensitivity = random.choices(DATA_SENSITIVITY, weights=SENSITIVITY_WEIGHTS, k=1)[0]

        employee_id = f"EMP-{i:06d}"  # synthetic ID, not a real employee
        department = random.choice(DEPARTMENTS)
        role = fake.job()
        ts = now - timedelta(
            days=random.randint(0, 90),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )
        prompt_text = build_prompt_text(fake, sensitivity)

        rows.append({
            "event_id": f"EVT-{i:07d}",
            "timestamp": ts.isoformat(),
            "employee_id": employee_id,
            "department": department,
            "role": role,
            "tool_name": tool_name,
            "tool_class": tool_class,   # sanctioned / unsanctioned (ground truth for discovery.py)
            "tool_risk": tool_risk,     # low / medium / high (ground truth for governance_score.py)
            "data_sensitivity": sensitivity,  # public / sensitive / critical
            "prompt_text": prompt_text,
        })
    return rows


def main():
    ap = argparse.ArgumentParser(description="Generate synthetic Shadow AI usage telemetry.")
    ap.add_argument("--n", type=int, default=2000, help="Number of synthetic events to generate.")
    ap.add_argument("--out", type=str, default="output/synthetic_usage.csv", help="Output CSV path.")
    ap.add_argument("--registry", type=str, default="config/known_endpoints.yaml", help="Tool registry YAML path.")
    ap.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")
    args = ap.parse_args()

    rows = generate(args.n, args.registry, seed=args.seed)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} synthetic events -> {args.out}")
    print("NOTE: 100% synthetic data. No real organizational data was used.")


if __name__ == "__main__":
    main()
