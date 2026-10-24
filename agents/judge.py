"""Judge — pure Python, NO LLM.

Applies weights (core.scoring), re-ranks, explains what changed (snapshot diff), estimates
uncertainty (core.sensitivity) and chooses the next test (core.sampling). Scores only come
from here — the LLM never sets or edits a score.
"""

from __future__ import annotations

from core.domain import LoadedPack
from core.policy import Policy
from core.state import IncidentState, Status


class Judge:
    def __init__(self, loaded_pack: LoadedPack, policy: Policy) -> None:
        self.loaded_pack = loaded_pack
        self.policy = policy

    def run(self, state: IncidentState) -> IncidentState:
        """Rank the current ledger; append a ranking snapshot; set the leader.

        INSUFFICIENT_EVIDENCE (weight below threshold) sets the status and emits no ranking.
        Other workflow transitions (DONE / AWAITING_EVIDENCE / ...) are driven by the
        workflow engine in S7 — the Judge only produces ranking outputs.
        """
        from core.scoring import InsufficientEvidenceError, rank

        previous = state.ranking_history[-1] if state.ranking_history else None
        try:
            result = rank(
                state.ledger,
                self.loaded_pack.pack,
                self.policy,
                round_no=state.round,
                previous=previous,
            )
        except InsufficientEvidenceError:
            state.status = Status.INSUFFICIENT_EVIDENCE
            return state
        state.leader = result.snapshot.leader
        state.ranking_history.append(result.snapshot)
        return state

    def assess_uncertainty(self, state: IncidentState, runs: int = 1000, seed: int = 0) -> IncidentState:
        """Seeded Monte Carlo weight sensitivity -> state.sensitivity. Implemented in S2b (Part D)."""
        from core import sensitivity as _sensitivity

        state.sensitivity = _sensitivity.sensitivity(
            state.ledger,
            self.loaded_pack.pack,
            runs=runs,
            cutoff=self.policy.separability_cutoff,
            seed=seed,
        )
        return state

    def choose_next_test(self, state: IncidentState) -> IncidentState:
        """Next-test table -> state.next_test. Implemented in Part E."""
        from core import sampling as _sampling

        if state.ranking_history:
            scores = state.ranking_history[-1].scores
            state.next_test = _sampling.recommend_next_test(scores, self.loaded_pack.pack)
        return state
