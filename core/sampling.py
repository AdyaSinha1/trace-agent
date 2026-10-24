"""Next-test ranking (docs/scoring.md) — HEURISTIC, not exact optimisation.

For each candidate test from the pack:
- expected information gain = expected entropy reduction, treating the current normalised
  evidence scores as a heuristic (uncalibrated) distribution over hypotheses and the pack's
  assumed outcome likelihoods as the outcome model;
- expected change in the top-two margin (secondary, easier to explain to judges);
- gain per cost, which is the ranking metric.
Returns the best test AND the full table, plus what each possible result would imply —
all derived from pack config, nothing hard-coded.
"""

from __future__ import annotations

import math
from typing import Dict, List

from core.domain import DomainPack
from core.state import NextTestRecommendation


def _entropy(weights: Dict[str, float]) -> float:
    total = sum(weights.values())
    if total <= 0:
        return 0.0
    h = 0.0
    for w in weights.values():
        p = w / total
        if p > 0:
            h -= p * math.log(p)
    return h


def _top_two_margin(weights: Dict[str, float]) -> float:
    ordered = sorted(weights.values(), reverse=True)
    if len(ordered) < 2:
        return 0.0
    return (ordered[0] - ordered[1]) / sum(weights.values())


def recommend_next_test(scores: Dict[str, float], pack: DomainPack) -> NextTestRecommendation:
    q = {h: s / 100.0 for h, s in scores.items()}
    current_entropy = _entropy(q)
    current_margin = _top_two_margin(q)

    rows: List[Dict[str, object]] = []
    for test in sorted(pack.tests, key=lambda t: t.id):
        outcomes = sorted({o for lh in test.outcome_likelihoods.values() for o in lh})
        p_outcome: Dict[str, float] = {
            o: sum(q[h] * test.outcome_likelihoods.get(h, {}).get(o, 0.0) for h in q)
            for o in outcomes
        }
        expected_entropy = 0.0
        expected_margin = 0.0
        for o in outcomes:
            p = p_outcome[o]
            if p <= 1e-12:
                continue
            posterior = {
                h: q[h] * test.outcome_likelihoods.get(h, {}).get(o, 0.0) / p for h in q
            }
            expected_entropy += p * _entropy(posterior)
            expected_margin += p * _top_two_margin(posterior)
        gain = current_entropy - expected_entropy
        cost = max(test.cost, 1e-9)
        implications = []
        for o in outcomes:
            best = sorted(
                pack.hypothesis_ids(),
                key=lambda h: (-test.outcome_likelihoods.get(h, {}).get(o, 0.0), h),
            )[0]
            likelihood = test.outcome_likelihoods.get(best, {}).get(o, 0.0)
            implications.append(
                f"'{o}' would most support '{best}' (assumed likelihood {likelihood:.2f})"
            )
        rows.append(
            {
                "test_id": test.id,
                "label": test.label,
                "cost": test.cost,
                "expected_info_gain": round(gain, 4),
                "expected_margin_change": round(expected_margin - current_margin, 4),
                "gain_per_cost": round(gain / cost, 4),
                "rationale": test.rationale,
                "implications": implications,
            }
        )

    rows.sort(key=lambda r: (-float(r["gain_per_cost"]), -float(r["expected_info_gain"]), str(r["test_id"])))
    best = rows[0]["test_id"] if rows else None
    rationale = (
        "Heuristic ranking, not exact optimisation: expected entropy reduction over the "
        "normalised evidence scores used as heuristic weights (secondary column: expected "
        "top-two margin change), ranked by gain per cost. Evidence scores, not probabilities."
    )
    return NextTestRecommendation(best_test=best, table=rows, rationale=rationale)
