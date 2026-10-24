"""Append-only evidence ledger (domain-agnostic). See AGENTS.md "Evidence ledger"."""

from __future__ import annotations

from enum import Enum
from typing import Dict, Iterable, List, Optional

from pydantic import BaseModel, Field

VERIFIED = 1.0
UNVERIFIED = 0.5


class EvidenceKind(str, Enum):
    OBSERVATION = "observation"
    TOOL_OUTPUT = "tool_output"
    AGENT_CLAIM = "agent_claim"
    INJECTED = "injected"
    ACTION = "action"


class EvidenceRecord(BaseModel):
    """One raw evidence item. Stores RAW observations only — no support/contradict labels."""

    id: str
    source: str
    source_group: str
    timestamp: str
    location: str
    observation: str
    kind: EvidenceKind
    reliability: float = UNVERIFIED  # verified = 1.0 | unverified = 0.5
    evidence_type: Optional[str] = None  # must match a pack evidence_type id; unknown => weight 0, flagged
    values: Dict[str, object] = Field(default_factory=dict)  # rule-matching payload (op/value)


class EvidenceLedger:
    """Append-only store: duplicate ids rejected, records never mutated or removed."""

    def __init__(self) -> None:
        self._records: List[EvidenceRecord] = []
        self._ids: set[str] = set()

    def append(self, record: EvidenceRecord) -> EvidenceRecord:
        if record.id in self._ids:
            raise ValueError(f"ledger is append-only: duplicate id {record.id!r}")
        self._records.append(record)
        self._ids.add(record.id)
        return record

    def get(self, record_id: str) -> Optional[EvidenceRecord]:
        if record_id not in self._ids:
            return None
        return next(r for r in self._records if r.id == record_id)

    def records(self, kinds: Optional[Iterable[EvidenceKind]] = None) -> tuple[EvidenceRecord, ...]:
        if kinds is None:
            return tuple(self._records)
        wanted = set(kinds)
        return tuple(r for r in self._records if r.kind in wanted)

    def ids(self) -> set[str]:
        return set(self._ids)

    def citations_valid(self, cited_ids: Iterable[str]) -> bool:
        """Every cited id must already exist in the ledger (invariant 3, docs/state.md)."""
        return all(cid in self._ids for cid in cited_ids)

    def __len__(self) -> int:
        return len(self._records)
