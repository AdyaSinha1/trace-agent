"""Seeded Monte Carlo sampling (S2b): reproducible weight factors in [0.5, 1.5]."""

from __future__ import annotations

from typing import Iterator, Sequence, Tuple


def weight_factors(
    keys: Sequence[str], runs: int, low: float = 0.5, high: float = 1.5, seed: int = 0
) -> Iterator[Tuple[str, Tuple[float, ...]]]:
    """Per run, one random factor per weight key. Seeded => reproducible. Implemented in S2b."""
    raise NotImplementedError("S2b")
