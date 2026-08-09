#!/usr/bin/env python3
"""
shade/mcp_tool_call_monitor.py

Scoped prototype: extends SHADE's monitoring concept from chat-tool prompt
text (what the core pipeline handles) to AGENT TOOL-CALLS -- the shape of
telemetry an MCP (Model Context Protocol) server or similar agent
framework actually produces. This is a different telemetry shape, not just
a bigger version of the existing one:

  Chat-tool event (core pipeline): free-text prompt, risk inferred from
  regex-detectable PII/secret patterns in that text.

  Agent tool-call event (this extension): a structured invocation --
  which MCP server, which METHOD on it (e.g. filesystem.write,
  email.send, database.query), and arguments -- where the risk is
  substantially about WHAT ACTION the method performs (read vs. write vs.
  execute) independent of whether the arguments happen to contain
  regex-detectable PII. A single call to `shell.execute` with an
  innocuous-looking argument string is still a fundamentally different
  risk than a `filesystem.read` call, in a way DLP pattern-matching on the
  argument text alone would miss entirely.

SCOPE, DELIBERATELY LIMITED:
- 100% synthetic MCP server/method registry and synthetic tool-call
  events, Faker-generated, no real MCP server is ever contacted and no
  network call is made -- same offline/zero-budget property as the rest
  of this repository.
- This models METHOD-LEVEL risk classification (read/write/execute) as
  the primary new signal, reusing shade/dlp_redact.py's existing regex patterns
  on the (synthetic) argument text as a secondary signal -- it does not
  attempt session-level agent behavior analysis, multi-step plan
  reasoning, or detection of an agent chaining calls to achieve an effect
  no single call would trigger on its own (a real and harder problem,
  explicitly out of scope here).
- Governance decisions reuse the SAME formal-verification approach as the
  core matrix (shade/verify_policy.py, same method as ADR 0001; see also ADR 0002 and
  ADR 0003, which graduated this module into shade/)
  over a new (method_risk_class x data_sensitivity) domain -- demonstrating
  that the verification approach generalizes to a second, differently-
  shaped governance table, not just the original one.

Usage:
    python shade/mcp_tool_call_monitor.py --n 500

Graduated into shade/ per docs/adr/0003-integrating-mcp-tool-call-monitor.md.
See that ADR for how shade/run_pipeline.py's opt-in
--include_mcp_monitoring flag invokes this module's functions directly
(as an independent parallel phase, not chained to core pipeline data) and
why the default output path convention changed from experiments/output/
to output/ upon graduation.
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from faker import Faker
from shade.dlp_redact import redact_text
from shade.verify_policy import verify_arbitrary_matrix

# Synthetic MCP server/method registry -- illustrative only, same spirit as
# config/known_endpoints.yaml but for agent tool-calls. method_risk_class
# is an author-assigned illustrative classification (read/write/execute),
# not derived from any real MCP server's actual behavior.
MCP_METHOD_REGISTRY = [
    {"server": "filesystem", "method": "read_file", "method_risk_class": "read"},
    {"server": "filesystem", "method": "write_file", "method_risk_class": "write"},
    {"server": "filesystem", "method": "delete_file", "method_risk_class": "execute"},
    {"server": "email", "method": "list_messages", "method_risk_class": "read"},
    {"server": "email", "method": "send_message", "method_risk_class": "write"},
    {"server": "database", "method": "query", "method_risk_class": "read"},
    {"server": "database", "method": "write_record", "method_risk_class": "write"},
    {"server": "shell", "method": "execute_command", "method_risk_class": "execute"},
    {"server": "browser", "method": "navigate", "method_risk_class": "read"},
    {"server": "browser", "method": "submit_form", "method_risk_class": "write"},
]

METHOD_RISK_CLASSES = ("read", "write", "execute")
DATA_SENSITIVITY_LEVELS = ("public", "sensitive", "critical")

# New decision matrix for the tool-call domain: (method_risk_class,
# data_sensitivity) -> action. Author-designed for this scaffold, modeled
# on the same severity logic as shade/governance_score.py's matrix (paper
# Section 4.4) but NOT identical to it -- execute-class actions against
# critical data are blocked outright, matching the intuition that an
# agent executing an irreversible action against sensitive data is at
# least as serious as a high-risk chat tool seeing the same data.
MCP_DECISION_MATRIX = {
    ("execute", "critical"): "BLOCK",
    ("execute", "sensitive"): "BLOCK_WITH_OVERRIDE",
    ("execute", "public"): "ALLOW_WITH_MONITORING",
    ("write", "critical"): "BLOCK_WITH_OVERRIDE",
    ("write", "sensitive"): "REDACT_THEN_ALLOW",
    ("write", "public"): "ALLOW",
    ("read", "critical"): "REDACT_THEN_ALLOW",
    ("read", "sensitive"): "ALLOW_WITH_MONITORING",
    ("read", "public"): "ALLOW",
}
KNOWN_ACTIONS = {"BLOCK", "BLOCK_WITH_OVERRIDE", "ALLOW", "REDACT_THEN_ALLOW", "ALLOW_WITH_MONITORING"}


def decide_tool_call(method_risk_class, data_sensitivity):
    return MCP_DECISION_MATRIX.get((method_risk_class, data_sensitivity), "ALLOW_WITH_MONITORING")


def generate_synthetic_tool_calls(n, seed=42):
    """100% synthetic MCP tool-call events. No real MCP server contacted."""
    import random
    random.seed(seed)
    fake = Faker()
    Faker.seed(seed)

    rows = []
    now = datetime.utcnow()
    for i in range(n):
        entry = random.choice(MCP_METHOD_REGISTRY)
        sensitivity = random.choices(DATA_SENSITIVITY_LEVELS, weights=[0.5, 0.3, 0.2], k=1)[0]

        if sensitivity == "critical":
            arg_text = f"path/target: {fake.file_path()} contact: {fake.email()}"
        elif sensitivity == "sensitive":
            arg_text = f"path/target: {fake.file_path()} note: {fake.sentence()}"
        else:
            arg_text = f"path/target: {fake.file_path()}"

        redacted_args, dlp_hits = redact_text(arg_text)
        action = decide_tool_call(entry["method_risk_class"], sensitivity)

        rows.append({
            "call_id": f"CALL-{i:07d}",
            "timestamp": (now - timedelta(minutes=random.randint(0, 10000))).isoformat(),
            "mcp_server": entry["server"],
            "method": entry["method"],
            "method_risk_class": entry["method_risk_class"],
            "data_sensitivity": sensitivity,
            "args_summary_redacted": redacted_args,
            "dlp_hits": json.dumps(dlp_hits),
            "governance_action": action,
        })
    return rows


def summarize(rows):
    return {
        "total_calls": len(rows),
        "by_server": dict(Counter(r["mcp_server"] for r in rows)),
        "by_method_risk_class": dict(Counter(r["method_risk_class"] for r in rows)),
        "by_governance_action": dict(Counter(r["governance_action"] for r in rows)),
        "calls_with_dlp_hit": sum(1 for r in rows if r["dlp_hits"] != "{}"),
        "note": (
            "100% synthetic MCP tool-call events; no real MCP server contacted, "
            "no network call made. method_risk_class (read/write/execute) is an "
            "author-assigned illustrative classification, not derived from any "
            "real MCP server's documented behavior. Session-level/multi-step "
            "agent plan reasoning is explicitly out of scope -- see this "
            "module's docstring."
        ),
    }


def main():
    ap = argparse.ArgumentParser(description="Synthetic MCP/agent tool-call monitoring scaffold.")
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=str, default="output/mcp_tool_calls.csv")
    ap.add_argument("--summary_out", type=str, default="output/mcp_tool_calls_summary.json")
    args = ap.parse_args()

    # Formally verify the new decision table before using it -- same
    # guardrail principle as shade/policy_proposer.py, applied
    # here to a hand-authored (not LLM-proposed) but still new-this-session
    # matrix, since ADR 0001's reasoning says any matrix should be checked,
    # not just LLM-proposed ones.
    violations = verify_arbitrary_matrix(MCP_DECISION_MATRIX, METHOD_RISK_CLASSES, DATA_SENSITIVITY_LEVELS, KNOWN_ACTIONS)
    if violations:
        raise SystemExit("MCP_DECISION_MATRIX failed formal verification:\n  - " + "\n  - ".join(violations))

    rows = generate_synthetic_tool_calls(args.n, seed=args.seed)
    report = summarize(rows)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    import csv
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    with open(args.summary_out, "w") as f:
        json.dump(report, f, indent=2)

    print(f"MCP_DECISION_MATRIX formally verified: PASS ({len(MCP_DECISION_MATRIX)} cells)")
    print(f"Generated {report['total_calls']} synthetic tool-call events -> {args.out}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
