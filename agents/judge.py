"""Judge — pure Python, NO LLM. Implemented in S2.

Applies weights, re-ranks, explains what changed (snapshot diff), estimates uncertainty
(seeded Monte Carlo) and chooses the next test. Scores only come from here.
"""

from __future__ import annotations

from core.domain import LoadedPack
from core.policy import Policy
from core.state import IncidentState


class Judge:
    def __init__(self, loaded_pack: LoadedPack, policy: Policy) -> None:
        self.loaded_pack = loaded_pack
        self.policy = policy

    def run(self, state: IncidentState) -> IncidentState:
        raise NotImplementedError("S2")
