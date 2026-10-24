"""Action execution — a deterministic tool, NOT a fourth agent. Runs only after human approval.

Creates a SIMULATED field work order (JSON, status "simulated") and a stakeholder
notification DRAFT (marked "DRAFT, NOT SENT"); nothing is ever sent. Each action is appended
to the ledger (kind = action). Rejection creates nothing. Read-only filesystems fall back to
a temp directory.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Protocol

from core.domain import DomainPack
from core.evidence import EvidenceKind, EvidenceRecord
from core.policy import Policy
from core.state import ActionRecord, Approval, IncidentState


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _writable_dir(preferred: Path) -> Path:
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        probe = preferred / ".probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return preferred
    except OSError:
        return Path(tempfile.gettempdir()) / "trace_outbox"


class ActionAdapter(Protocol):
    def create_work_order(self, spec: Dict[str, object]) -> Dict[str, object]: ...

    def draft_notification(self, spec: Dict[str, object]) -> Dict[str, object]: ...


class FileOutboxAdapter:
    """Writes JSON/Markdown artifacts under outbox/ and returns their payloads."""

    def __init__(self, base_dir: Path | str = Path("outbox")) -> None:
        self.base_dir = _writable_dir(Path(base_dir))

    def create_work_order(self, spec: Dict[str, object]) -> Dict[str, object]:
        directory = _writable_dir(self.base_dir / "work_orders")
        work_order = {
            "id": spec["id"],
            "test": spec["test"],
            "location": spec["location"],
            "parameter": spec["parameter"],
            "rationale": spec["rationale"],
            "cited_ledger_ids": spec["cited_ledger_ids"],
            "approver": spec["approver"],
            "timestamp": spec["timestamp"],
            "status": "simulated",
        }
        path = directory / f"{work_order['id']}.json"
        path.write_text(json.dumps(work_order, indent=2), encoding="utf-8")
        return {"record": work_order, "path": str(path)}

    def draft_notification(self, spec: Dict[str, object]) -> Dict[str, object]:
        directory = _writable_dir(self.base_dir / "notifications")
        path = directory / f"{spec['id']}.md"
        path.write_text(str(spec["text"]), encoding="utf-8")
        return {
            "record": {"id": spec["id"], "path": str(path), "status": "DRAFT, NOT SENT"},
            "path": str(path),
        }


class TicketingAdapter:
    """Stub for a real ticketing system (post-hackathon). Never sends anything."""

    def __init__(self, file_adapter: FileOutboxAdapter) -> None:
        self.file_adapter = file_adapter

    def create_work_order(self, spec: Dict[str, object]) -> Dict[str, object]:
        raise NotImplementedError("post-hackathon stub: ticketing integration")

    def draft_notification(self, spec: Dict[str, object]) -> Dict[str, object]:
        raise NotImplementedError("post-hackathon stub: ticketing integration")


def run_approved_actions(
    state: IncidentState,
    pack: DomainPack,
    policy: Policy,
    adapter: ActionAdapter | None,
    approver: str,
) -> List[ActionRecord]:
    """Approval gate: raises unless state.approval == approved. Rejection creates nothing."""
    if state.approval != Approval.APPROVED:
        raise PermissionError("actions require approval == approved")
    adapter = adapter if adapter is not None else FileOutboxAdapter()
    snapshot = state.ranking_history[-1]
    cited = list(snapshot.evidence_ids[:8])
    scores = ", ".join(f"{h}={s:.0f}" for h, s in sorted(snapshot.scores.items(), key=lambda kv: -kv[1]))
    test_id = state.next_test.best_test if state.next_test else None
    actions: List[ActionRecord] = []

    if test_id and "create_work_order" in policy.allowed_actions:
        test = next(t for t in pack.tests if t.id == test_id)
        spec = {
            "id": f"wo-{state.scenario_id}-r{state.round}",
            "test": test.label,
            "location": "field (simulated)",
            "parameter": test.id,
            "rationale": test.rationale,
            "cited_ledger_ids": cited,
            "approver": approver,
            "timestamp": _now(),
        }
        result = adapter.create_work_order(spec)
        wo_id = str(result["record"]["id"])
        actions.append(ActionRecord(action_id=wo_id, kind="work_order", path=str(result["path"]), cited_ids=cited, approver=approver, timestamp=_now()))
        state.ledger.append(
            EvidenceRecord(
                id=f"{state.scenario_id}:act:{wo_id}",
                source="action_tool",
                source_group="actions",
                timestamp=_now(),
                location=str(result["path"]),
                observation=f"SIMULATED work order {wo_id} created for test '{test_id}' (approved by {approver}); nothing was sent",
                kind=EvidenceKind.ACTION,
                reliability=1.0,
                values={"cites": cited},
            )
        )

    if "draft_notification" in policy.allowed_actions:
        template = pack.action_templates.notification
        body = template.format(
            id=f"nf-{state.scenario_id}-r{state.round}",
            cited_ids=", ".join(cited) if cited else "none",
            leader=snapshot.leader or "n/a",
        )
        text = (
            "DRAFT, NOT SENT\n\n"
            f"{body}\n\n"
            f"Leader: {snapshot.leader or 'n/a'}. Evidence scores, not probabilities: {scores}.\n"
            "Data is simulated; no source is confirmed.\n"
            f"Cited evidence: {', '.join(cited) if cited else 'none'}.\n"
            "This draft is never sent; a human approves or rejects."
        )
        result = adapter.draft_notification({"id": f"nf-{state.scenario_id}-r{state.round}", "text": text})
        nf_id = str(result["record"]["id"])
        actions.append(ActionRecord(action_id=nf_id, kind="notification_draft", path=str(result["path"]), cited_ids=cited, approver=approver, timestamp=_now()))
        state.ledger.append(
            EvidenceRecord(
                id=f"{state.scenario_id}:act:{nf_id}",
                source="action_tool",
                source_group="actions",
                timestamp=_now(),
                location=str(result["path"]),
                observation="notification DRAFT, NOT SENT (never sent; awaiting nothing — human decision already recorded)",
                kind=EvidenceKind.ACTION,
                reliability=1.0,
                values={"cites": cited},
            )
        )
    return actions
