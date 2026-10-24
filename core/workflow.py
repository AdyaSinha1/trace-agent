"""Incident workflow / state machine (docs/state.md). Implemented in S7.

LangGraph vs plain Python is decided at S7: LangGraph only if the state-machine tests pass
within a hard ~10-minute wall-clock budget (one quick retry allowed), else plain Python —
described accurately in the README.
"""

from __future__ import annotations

from core.domain import LoadedPack
from core.evidence import EvidenceRecord
from core.llm import LLMClient
from core.policy import Policy
from core.state import IncidentState


class WorkflowEngine:
    def __init__(
        self,
        loaded_pack: LoadedPack,
        policy: Policy,
        llm: LLMClient,
        action_adapter=None,
    ) -> None:
        self.loaded_pack = loaded_pack
        self.policy = policy
        self.llm = llm
        self.action_adapter = action_adapter

    def run(self, scenario: dict) -> IncidentState:
        """INIT -> INVESTIGATING -> CHALLENGING -> JUDGING -> ... (docs/state.md). Implemented in S7."""
        raise NotImplementedError("S7")

    def inject_evidence(self, state: IncidentState, record: EvidenceRecord) -> IncidentState:
        """AWAITING_EVIDENCE -> INVESTIGATING: ledger append, round + 1 (max-rounds cap). S7."""
        raise NotImplementedError("S7")
