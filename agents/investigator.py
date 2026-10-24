"""Investigator (LLM + deterministic Python tools). Implemented in S5 (templates first).

Reads records, detects anomalies with deterministic Python, proposes the pack's three
hypotheses with supporting evidence IDs. On LLM failure: template hypotheses, recorded in
the ledger. Offline mode uses templates only.
"""

from __future__ import annotations

from core.domain import LoadedPack
from core.evidence import EvidenceLedger
from core.llm import LLMClient
from core.state import HypothesisRef


class Investigator:
    def __init__(self, loaded_pack: LoadedPack, llm: LLMClient) -> None:
        self.loaded_pack = loaded_pack
        self.llm = llm

    def propose(self, ledger: EvidenceLedger) -> list[HypothesisRef]:
        raise NotImplementedError("S5")
