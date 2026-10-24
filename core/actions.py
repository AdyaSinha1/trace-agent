"""Action execution — a deterministic tool, NOT a fourth agent. Runs only after human approval.

FileOutboxAdapter: simulated work orders -> outbox/work_orders/ (JSON, status "simulated"),
notification drafts -> outbox/notifications/ (marked "DRAFT, NOT SENT"; nothing is ever sent).
Implemented in S7.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Protocol


class ActionAdapter(Protocol):
    def create_work_order(self, spec: Dict[str, object]) -> Dict[str, object]: ...

    def draft_notification(self, spec: Dict[str, object]) -> Dict[str, object]: ...


class FileOutboxAdapter:
    """Writes JSON artifacts under outbox/ and returns their ActionRecord payloads. S7."""

    def __init__(self, base_dir: Path | str = Path("outbox")) -> None:
        self.base_dir = Path(base_dir)

    def create_work_order(self, spec: Dict[str, object]) -> Dict[str, object]:
        raise NotImplementedError("S7")

    def draft_notification(self, spec: Dict[str, object]) -> Dict[str, object]:
        raise NotImplementedError("S7")


class TicketingAdapter:
    """Stub for a real ticketing system (optional, post-hackathon). Never sends anything."""

    def __init__(self, file_adapter: FileOutboxAdapter) -> None:
        self.file_adapter = file_adapter

    def create_work_order(self, spec: Dict[str, object]) -> Dict[str, object]:
        raise NotImplementedError("post-hackathon stub")

    def draft_notification(self, spec: Dict[str, object]) -> Dict[str, object]:
        raise NotImplementedError("post-hackathon stub")
