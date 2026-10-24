"""Outcome report — Markdown per incident (UI adds a download button).

Contents: decision record (what, why with cited IDs, uncertainty and separability, who
approved, model/version used or "offline templates"), ranking history, contradictions with
citations, next test, actions, limitations. Every ledger ID the report cites is printed in
one canonical "Cited ledger IDs" line and all come from state (they exist by construction).
"""

from __future__ import annotations

from typing import List

from core.domain import DomainPack
from core.state import IncidentState

LIMITATIONS = (
    "Limitations: all data is simulated; weights are expert-assigned priors (ACH practice), "
    "not fitted; scores are evidence scores, NOT probabilities; evaluation runs on simulated "
    "scenarios and gives no real-world validation; a narrow margin is never a confident "
    "attribution; the next-test choice is a heuristic ranking, not exact optimisation; "
    "nothing is ever sent — alerts are drafts a human approves or rejects."
)


def _model_id(state: IncidentState) -> str:
    for record in state.ledger.records():
        if record.id.endswith("inv:hyp") or ":inv:hyp:" in record.id:
            return str(record.values.get("model_id") or "unknown")
    return "offline templates"


def build_report(state: IncidentState, pack: DomainPack) -> str:
    lines: List[str] = []
    lines.append(f"# Incident report — {state.scenario_id} ({pack.name})")
    lines.append("")
    lines.append("> Simulated data. Evidence scores, not probabilities. No source is confirmed.")
    lines.append("")

    lines.append("## Decision record")
    if state.ranking_history:
        snapshot = state.ranking_history[-1]
        leader_label = pack.hypothesis_label(snapshot.leader or "n/a")
        lines.append(f"- Final leader: **{leader_label}** (`{snapshot.leader}`)")
        ranked = ", ".join(f"{pack.hypothesis_label(h)}: {s:.0f}" for h, s in sorted(snapshot.scores.items(), key=lambda kv: -kv[1]))
        lines.append(f"- Evidence scores (not probabilities): {ranked}")
        lines.append(f"- Why: {' | '.join(snapshot.explanation[:6])}")
    else:
        lines.append("- No ranking was emitted (INSUFFICIENT_EVIDENCE or workflow not judged).")
    if state.sensitivity is not None:
        s = state.sensitivity
        lines.append(
            f"- Uncertainty and separability: **{s.label}** — leader stays leader in "
            f"{s.leader_stability:.0%} of {s.runs} seeded runs; mean rank "
            f"{ {h: round(r, 2) for h, r in s.mean_rank.items()} }; mean top-two margin {s.top_two_margin:.1f}."
        )
    approver = state.actions[0].approver if state.actions else None
    approval_text = {
        "approved": f"approved by {approver}" if approver else "approved",
        "rejected": "rejected by a human (no actions executed)",
        "pending": "awaiting human approval",
        "none": "no approval requested",
    }.get(state.approval.value if hasattr(state.approval, "value") else str(state.approval), str(state.approval))
    lines.append(f"- Approval: {approval_text}")
    lines.append(f"- Model/version used: {_model_id(state)}")
    lines.append("")

    lines.append("## Ranking history (one snapshot per Judge run)")
    for i, snap in enumerate(state.ranking_history):
        ranked = ", ".join(f"{h}={s:.0f}" for h, s in sorted(snap.scores.items(), key=lambda kv: -kv[1]))
        lines.append(f"- Run {i + 1} (round {snap.round}): leader **{pack.hypothesis_label(snap.leader or 'n/a')}** — {ranked}")
    lines.append("")

    lines.append("## Contradictions (with citations)")
    contradictions = [f for f in state.challenger_findings if f.kind == "contradiction"]
    if contradictions:
        for f in contradictions:
            lines.append(f"- {f.text} (cites: {', '.join(f'`{i}`' for i in f.cited_ids) or 'none'})")
    else:
        lines.append("- None found.")
    lines.append("")
    lines.append("## Missing evidence")
    missing = [f for f in state.challenger_findings if f.kind == "missing_evidence"]
    if missing:
        for f in missing:
            lines.append(f"- {f.text}")
    else:
        lines.append("- None flagged.")
    lines.append("")

    lines.append("## Next test (heuristic ranking, not exact optimisation)")
    if state.next_test and state.next_test.best_test:
        test = next((t for t in pack.tests if t.id == state.next_test.best_test), None)
        lines.append(f"- Recommended: **{test.label if test else state.next_test.best_test}** (cost {test.cost if test else '?'})")
        for row in state.next_test.table[:6]:
            lines.append(
                f"  - {row['test_id']}: expected info gain {row['expected_info_gain']}, "
                f"expected top-two margin change {row['expected_margin_change']}, gain per cost {row['gain_per_cost']}"
            )
        lines.append(f"- {state.next_test.rationale}")
    else:
        lines.append("- No next test available.")
    lines.append("")

    lines.append("## Approvals and actions")
    if state.alert_draft is not None:
        lines.append(f"- Alert draft requested at {state.alert_draft.created_at} (drafts are NEVER sent).")
    if state.actions:
        for action in state.actions:
            lines.append(f"- {action.kind} `{action.action_id}` -> {action.path} (approved by {action.approver})")
    elif state.approval.value == "rejected":
        lines.append("- Rejected: no actions were created.")
    else:
        lines.append("- No actions (nothing is ever sent).")
    lines.append("")
    lines.append(f"## {LIMITATIONS}")
    lines.append("")

    cited_ids = sorted(
        {cid for f in state.challenger_findings for cid in f.cited_ids}
        | (set(state.alert_draft.cited_ids) if state.alert_draft else set())
        | {cid for a in state.actions for cid in a.cited_ids}
        | (set(state.ranking_history[-1].evidence_ids) if state.ranking_history else set())
    )
    existing = state.ledger.ids()
    cited_ids = [cid for cid in cited_ids if cid in existing]  # report cites only existing IDs
    lines.append(f"Cited ledger IDs: {', '.join(cited_ids) if cited_ids else 'none'}")
    return "\n".join(lines)
