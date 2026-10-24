"""Seeded Monte Carlo weight sensitivity (docs/scoring.md).

Each run multiplies every pack evidence-type weight by a random factor in [0.5, 1.5]
(one factor per evidence type per run, applied to all its contributions), re-computes the
grouped/normalised evidence scores, and records the leader. Reports the leader-stays-leader
frequency, mean rank per hypothesis, mean top-two margin, and a separable/not-separable
label at the configurable cut-off. Seeded RNG -> reproducible.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np

from core.domain import DomainPack
from core.evidence import EvidenceLedger
from core.scoring import LABEL, assess, group_strongest, normalise
from core.state import SensitivityResult


def _leader_and_margin(raw: Dict[str, float]) -> tuple[str, float, Dict[str, float]]:
    scores = normalise(raw)
    ordered = sorted(scores, key=lambda h: (-scores[h], h))
    margin = scores[ordered[0]] - scores[ordered[1]]
    ranks = {h: i + 1 for i, h in enumerate(ordered)}
    return ordered[0], margin, ranks


def sensitivity(
    ledger: EvidenceLedger,
    pack: DomainPack,
    runs: int = 1000,
    low: float = 0.5,
    high: float = 1.5,
    cutoff: float = 0.7,
    seed: int = 0,
) -> SensitivityResult:
    if runs < 1:
        raise ValueError("runs must be >= 1")
    assessment = assess(ledger, pack)
    base_groups, base_raw = group_strongest(assessment, pack)
    base_contribs = assessment.contributions

    # Factor keys: every pack evidence type (sorted for determinism).
    type_ids = sorted(et.id for et in pack.evidence_types)
    rng = np.random.default_rng(seed)
    factors = rng.uniform(low, high, size=(runs, len(type_ids)))
    factor_index = {tid: i for i, tid in enumerate(type_ids)}

    # Contribution lookup: (hyp, group) -> list of (type_id, signed_base_weight).
    per_group: Dict[str, Dict[str, List[tuple]]] = {}
    for hyp, contribs in base_contribs.items():
        for c in contribs:
            per_group.setdefault(hyp, {}).setdefault(c.group, []).append((c.evidence_type, c.signed_weight))

    base_leader, _, _ = _leader_and_margin(base_raw)

    leader_wins = 0
    rank_sum: Dict[str, float] = {hyp: 0.0 for hyp in pack.hypothesis_ids()}
    margin_sum = 0.0
    for run in range(runs):
        raw: Dict[str, float] = {}
        for hyp in pack.hypothesis_ids():
            total = 0.0
            for group, items in per_group.get(hyp, {}).items():
                strongest = None
                for tid, w in items:
                    scaled = w * factors[run][factor_index[tid]]
                    if strongest is None or (abs(scaled), scaled) > (abs(strongest), strongest):
                        strongest = scaled
                total += strongest or 0.0
            raw[hyp] = max(0.1, 1.0 + total)
        leader, margin, ranks = _leader_and_margin(raw)
        if leader == base_leader:
            leader_wins += 1
        margin_sum += margin
        for hyp, r in ranks.items():
            rank_sum[hyp] += r

    stability = leader_wins / runs
    separable = stability >= cutoff
    return SensitivityResult(
        runs=runs,
        leader_stability=round(stability, 4),
        mean_rank={hyp: round(rank_sum[hyp] / runs, 3) for hyp in pack.hypothesis_ids()},
        top_two_margin=round(margin_sum / runs, 4),
        separable=separable,
        label="separable" if separable else "not separable",
    )
