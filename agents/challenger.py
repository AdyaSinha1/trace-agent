"""Challenger (deterministic rules first, then optional LLM). Implemented in S6.

Receives ONLY the leading hypothesis and the raw ledger evidence — never the Investigator's
reasoning. Returns contradictions and missing evidence. It never states a conclusion and
never touches scores.
"""

from __future__ import annotations

from core.domain import LoadedPack
from core.evidence import EvidenceLedger
from core.llm import LLMClient
from core.state import Finding


class Challenger:
    def __init__(self, loaded_pack: LoadedPack, llm: LLMClient | None = None) -> None:
        self.loaded_pack = loaded_pack
        self.llm = llm

    def challenge(self, leader_id: str, ledger: EvidenceLedger) -> list[Finding]:
        raise NotImplementedError("S6")
