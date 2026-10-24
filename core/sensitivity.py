"""Seeded Monte Carlo weight sensitivity (S2b) — docs/scoring.md."""

from __future__ import annotations

from core.domain import DomainPack
from core.evidence import EvidenceLedger
from core.state import SensitivityResult


def sensitivity(
    ledger: EvidenceLedger,
    pack: DomainPack,
    runs: int = 1000,
    low: float = 0.5,
    high: float = 1.5,
    cutoff: float = 0.7,
    seed: int = 0,
) -> SensitivityResult:
    """1000 seeded runs, each weight x random factor in [low, high].

    Reports leader-stays-leader frequency, mean rank per hypothesis, top-two margin, and a
    separable/not-separable label at the cut-off. A narrow margin is NEVER reported as a
    confident attribution. Implemented in S2b.
    """
    raise NotImplementedError("S2b")
