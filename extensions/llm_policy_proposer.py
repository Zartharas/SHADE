#!/usr/bin/env python3
"""
extensions/llm_policy_proposer.py

Scoped prototype: an LLM PROPOSES changes/additions to the governance
decision matrix (e.g. a new data_sensitivity tier, or a rationale for
reconsidering an existing cell); the proposal is NEVER auto-applied. It
must pass a formal verification gate (generalized from verify_policy.py's
method) before being written out as a reviewable candidate matrix, and a
human must manually copy it into governance_score.py to adopt it. This is
the guardrail: formal verification catches structural defects (missing
cells, conflicting actions, unknown action labels) that an LLM proposal
could introduce, exactly the failure mode verify_policy.py exists to catch
for the hand-authored matrix.

SCOPE, DELIBERATELY LIMITED:
- No live LLM API call is made anywhere in this repository. SHADE's README
  states the pipeline "makes no network calls" as a project-wide property;
  wiring in a real API call would break that property and would also cost
  real money this zero-budget project doesn't spend. Instead, this module
  defines a small `PolicyProposerBackend` interface with ONE implementation
  shipped: `HeuristicMockBackend`, a deterministic, offline, rule-based
  stand-in that produces a plausible-shaped proposal so the surrounding
  pipeline (propose -> verify -> human review) can be exercised and tested
  end to end without any API dependency.
- Wiring a real LLM behind this interface (e.g. the Anthropic or OpenAI
  API) is future work, intentionally left unimplemented here -- see
  "Wiring in a real LLM backend" below. Doing so would require its own
  evaluation of proposal quality against real policy-design judgment,
  which is a distinct research question this scaffold does not attempt to
  answer.
- This does NOT claim to have evaluated whether LLM-proposed policy is
  good policy. It claims only that IF an LLM (or anything else) proposes a
  policy, that proposal can be mechanically checked for the same
  structural properties (completeness, non-conflict, known-action
  vocabulary) verify_policy.py already checks for the hand-authored
  matrix -- extended here to work over an arbitrary domain, not just the
  fixed 3x3 one.

Wiring in a real LLM backend (not implemented): subclass
PolicyProposerBackend, call your provider's API in propose(), and parse
its response into the same {(axis1_val, axis2_val): (action, reason)}
shape HeuristicMockBackend returns. Everything downstream (verification,
review-file writing) is backend-agnostic already.

Usage (mock backend only, no API key/network required):
    python extensions/llm_policy_proposer.py --context "add a 'regulated' data_sensitivity tier for GDPR-scoped data"
"""
import argparse
import itertools
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from governance_score import DECISION_MATRIX, DECISION_REASONS
from verify_policy import KNOWN_ACTIONS, TOOL_RISK_LEVELS, DATA_SENSITIVITY_LEVELS
from extensions._verification_core import verify_arbitrary_matrix


# (verify_arbitrary_matrix now lives in extensions/_verification_core.py,
# shared with extensions/mcp_tool_call_monitor.py)


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------
class PolicyProposerBackend:
    def propose(self, current_matrix, current_reasons, context, axis1_values, axis2_values):
        """Must return (proposed_matrix, proposed_reasons, rationale_note)
        where proposed_matrix is {(a1,a2): action} covering the FULL
        axis1_values x axis2_values domain, proposed_reasons is
        {(a1,a2): reason_string}, and rationale_note is a short string
        explaining the overall proposal."""
        raise NotImplementedError


class HeuristicMockBackend(PolicyProposerBackend):
    """
    Deterministic, offline, no-API-key stand-in for a real LLM call. Uses a
    simple fixed heuristic (more severe axis-1/axis-2 values skew toward
    stricter actions) so the propose -> verify -> review pipeline can be
    exercised and tested without a network call or API cost. This is a
    MOCK: it does not claim to produce policy of the quality a real LLM
    (or a human policy designer) would -- see this module's docstring.
    """
    SEVERITY_ORDER = ["high", "critical", "medium", "sensitive", "low", "public", "regulated", "restricted"]

    def _severity_rank(self, value):
        # Unseen values are treated as maximally severe (fail-safe default
        # for the mock: better to over-restrict an unrecognized label than
        # under-restrict it). This is a deliberate, documented heuristic,
        # not a claim about real risk ordering.
        try:
            return self.SEVERITY_ORDER.index(value)
        except ValueError:
            return -1

    def propose(self, current_matrix, current_reasons, context, axis1_values, axis2_values):
        proposed_matrix = {}
        proposed_reasons = {}
        for a1 in axis1_values:
            for a2 in axis2_values:
                key = (a1, a2)
                if key in current_matrix:
                    proposed_matrix[key] = current_matrix[key]
                    proposed_reasons[key] = current_reasons.get(key, f"carried over from existing matrix for {key}")
                    continue
                # New cell (e.g. a newly proposed axis value): heuristic
                # fallback, always fail-safe toward a stricter action, NEVER
                # silently ALLOW for an unrecognized combination.
                rank1, rank2 = self._severity_rank(a1), self._severity_rank(a2)
                if rank1 <= 1 or rank2 <= 1:  # "high"/"critical"-adjacent
                    action = "BLOCK_WITH_OVERRIDE"
                elif rank1 <= 3 or rank2 <= 3:
                    action = "REDACT_THEN_ALLOW"
                else:
                    action = "ALLOW_WITH_MONITORING"
                proposed_matrix[key] = action
                proposed_reasons[key] = (
                    f"[MOCK PROPOSAL, needs human review] {action} for new/unrated "
                    f"combination {key}, context: {context!r}. Heuristic fail-safe "
                    f"default, not a reasoned policy judgment -- see rationale note."
                )
        rationale = (
            f"[HeuristicMockBackend] Deterministic mock proposal for context "
            f"{context!r}. New/unmatched cells default to the strictest "
            f"plausible action given a simple severity heuristic. This is NOT "
            f"a substitute for human policy review -- see this module's "
            f"docstring for why no real LLM is called here."
        )
        return proposed_matrix, proposed_reasons, rationale


# ---------------------------------------------------------------------------
# Orchestration: propose -> verify -> write reviewable candidate file.
# Never touches governance_score.py.
# ---------------------------------------------------------------------------
def propose_and_verify(context, backend=None, extra_axis1=None, extra_axis2=None, out_path="experiments/output/policy_proposal.json"):
    backend = backend or HeuristicMockBackend()
    axis1_values = list(TOOL_RISK_LEVELS) + list(extra_axis1 or [])
    axis2_values = list(DATA_SENSITIVITY_LEVELS) + list(extra_axis2 or [])

    proposed_matrix, proposed_reasons, rationale = backend.propose(
        DECISION_MATRIX, DECISION_REASONS, context, axis1_values, axis2_values
    )

    violations = verify_arbitrary_matrix(proposed_matrix, axis1_values, axis2_values, KNOWN_ACTIONS)

    result = {
        "context": context,
        "backend": type(backend).__name__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "axis1_values": axis1_values,
        "axis2_values": axis2_values,
        "proposed_matrix": {f"{k[0]}|{k[1]}": v for k, v in proposed_matrix.items()},
        "proposed_reasons": {f"{k[0]}|{k[1]}": v for k, v in proposed_reasons.items()},
        "rationale": rationale,
        "formal_verification": {
            "status": "PASS" if not violations else "FAIL",
            "violations": violations,
        },
        "status": "REJECTED_FAILED_VERIFICATION" if violations else "CANDIDATE_PENDING_HUMAN_REVIEW",
        "note": (
            "This proposal was NOT applied to governance_score.py. A human "
            "must review proposed_matrix/proposed_reasons and manually "
            "update DECISION_MATRIX/DECISION_REASONS if adopted. See "
            "docs/extensions.md for why auto-apply is out of scope."
        ),
    }

    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)

    return result


def main():
    ap = argparse.ArgumentParser(description="Propose a governance policy change (mock backend, no API call) and formally verify it before writing a reviewable candidate.")
    ap.add_argument("--context", type=str, default="no specific context provided", help="Free-text description of what's being proposed/why.")
    ap.add_argument("--add_tool_risk", type=str, default=None, help="Optional new tool_risk-axis value to include in the proposal domain.")
    ap.add_argument("--add_data_sensitivity", type=str, default=None, help="Optional new data_sensitivity-axis value to include in the proposal domain.")
    ap.add_argument("--out", type=str, default="experiments/output/policy_proposal.json")
    args = ap.parse_args()

    extra_axis1 = [args.add_tool_risk] if args.add_tool_risk else None
    extra_axis2 = [args.add_data_sensitivity] if args.add_data_sensitivity else None

    result = propose_and_verify(args.context, extra_axis1=extra_axis1, extra_axis2=extra_axis2, out_path=args.out)
    print(f"Status: {result['status']}")
    print(f"Formal verification: {result['formal_verification']['status']}")
    if result["formal_verification"]["violations"]:
        for v in result["formal_verification"]["violations"]:
            print(f"  - {v}")
    print(f"Candidate written -> {args.out}")


if __name__ == "__main__":
    main()
