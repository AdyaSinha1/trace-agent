"""Evidence scoring (docs/scoring.md). Implemented in S2 — the Judge is its only caller."""

from __future__ import annotations

from core.domain import DomainPack
from core.evidence import EvidenceLedger
from core.policy import Policy
from core.state import RankingSnapshot


class InsufficientEvidenceError(Exception):
    """Total evidence weight below policy.min_total_weight -> no ranking is emitted."""


def rank(ledger: EvidenceLedger, pack: DomainPack, policy: Policy) -> RankingSnapshot:
    """raw_h = max(0.1, 1.0 + sum(signed_weight * reliability)) over independent source_groups;
    normalise to 100. Scores are EVIDENCE SCORES, NOT PROBABILITIES. Implemented in S2."""
    raise NotImplementedError("S2")
