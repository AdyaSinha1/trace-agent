"""Evidence scoring (docs/scoring.md). Pure Python, domain-agnostic — the Judge is its only caller.

raw_h = max(0.1, 1.0 + sum(signed_weight x reliability)) over INDEPENDENT source_groups
(within a group only the strongest signed contribution per hypothesis counts), normalised
to 100. Every output is labelled: these are EVIDENCE SCORES, NOT PROBABILITIES.

Rule semantics (deterministic):
- A record matches a pack relation rule when rule.evidence_type == record.evidence_type and
  rule.when holds against record.values["value"].
- Per (record, hypothesis): if rules both support and contradict -> the pair cancels (net 0)
  and the record id is flagged as conflicting.
- Per (hypothesis, source_group): the contribution with the largest |value| counts (ties ->
  the positive one). This is the correlated-observations rule: ten readings from one sensor
  cannot count ten times.
- Unknown evidence type: weight 0, flagged (runtime-supplied evidence can never crash the app).
- Total evidence weight (sum of weight x reliability over known-type records) below
  policy.min_total_weight -> InsufficientEvidenceError (status INSUFFICIENT_EVIDENCE, no ranking).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.domain import Condition, DomainPack
from core.evidence import EvidenceLedger, EvidenceRecord
from core.policy import Policy
from core.state import RankingSnapshot

LABEL = "evidence scores, not probabilities"


class InsufficientEvidenceError(Exception):
    """Total evidence weight below policy.min_total_weight -> no ranking is emitted."""


@dataclass
class Contribution:
    group: str
    evidence_type: str
    record_id: str
    signed_weight: float  # weight x reliability, signed by rule effect


@dataclass
class Assessment:
    contributions: Dict[str, List[Contribution]] = field(default_factory=dict)
    total_weight: float = 0.0
    unknown_types: List[str] = field(default_factory=list)
    conflicting_records: List[str] = field(default_factory=list)


def _matches(condition: Condition, record: EvidenceRecord) -> bool:
    value = record.values.get("value")
    op, target = condition.op, condition.value
    try:
        if op == "eq":
            return value == target
        if op == "ne":
            return value != target
        if op == "contains":
            return str(target) in str(value)
        if value is None:
            return False
        v, t = float(value), float(target)  # numeric comparisons
    except (TypeError, ValueError):
        return False
    return {"gt": v > t, "gte": v >= t, "lt": v < t, "lte": v <= t}[op]


def assess(ledger: EvidenceLedger, pack: DomainPack) -> Assessment:
    """Resolve every record to per-hypothesis signed contributions via pack rules."""
    rules_by_type: Dict[str, list] = {}
    for rule in pack.relation_rules:
        rules_by_type.setdefault(rule.evidence_type, []).append(rule)

    assessment = Assessment()
    for record in ledger.records():
        et_def = pack.evidence_type(record.evidence_type or "")
        if et_def is None or et_def.weight == 0:
            if record.evidence_type and record.evidence_type not in assessment.unknown_types:
                assessment.unknown_types.append(record.evidence_type)
            continue  # unknown type: weight 0, flagged
        weight = et_def.weight * record.reliability
        assessment.total_weight += abs(weight)
        for hypothesis_id in sorted(pack.hypothesis_ids()):
            effects = {
                eff
                for rule in rules_by_type.get(record.evidence_type or "", [])
                if hypothesis_id in rule.effects and _matches(rule.when, record)
                for eff in [rule.effects[hypothesis_id]]
            }
            if not effects:
                continue
            if effects == {"supports", "contradicts"}:
                if record.id not in assessment.conflicting_records:
                    assessment.conflicting_records.append(record.id)
                continue  # conflicting rules on one record cancel
            sign = 1.0 if effects == {"supports"} else -1.0
            assessment.contributions.setdefault(hypothesis_id, []).append(
                Contribution(record.source_group, record.evidence_type or "", record.id, sign * weight)
            )
    return assessment


def group_strongest(assessment: Assessment, pack: DomainPack) -> Tuple[Dict[str, Dict[str, float]], Dict[str, float]]:
    """One vote per (hypothesis, source_group): the strongest signed contribution."""
    groups: Dict[str, Dict[str, float]] = {}
    raw: Dict[str, float] = {}
    for hyp in pack.hypothesis_ids():
        by_group: Dict[str, float] = {}
        for c in assessment.contributions.get(hyp, []):
            current = by_group.get(c.group)
            if current is None or (abs(c.signed_weight), c.signed_weight) > (abs(current), current):
                by_group[c.group] = c.signed_weight
        groups[hyp] = by_group
        raw[hyp] = max(0.1, 1.0 + sum(by_group.values()))
    return groups, raw


def normalise(raw: Dict[str, float]) -> Dict[str, float]:
    total = sum(raw.values())
    return {h: value / total * 100.0 for h, value in raw.items()}


def _fmt_delta(before: float, after: float) -> str:
    return f"{before:.1f} -> {after:.1f} ({after - before:+.1f})"


def _explanation(
    scores: Dict[str, float],
    groups: Dict[str, Dict[str, float]],
    assessment: Assessment,
    previous: Optional[RankingSnapshot],
    contributing_ids: List[str],
    unverified_count: int,
) -> List[str]:
    lines = [f"Scores are {LABEL} (normalised to 100 across hypotheses)."]
    if assessment.unknown_types:
        lines.append(f"Unknown evidence type(s) given weight 0 and flagged: {assessment.unknown_types}")
    if assessment.conflicting_records:
        lines.append(f"Conflicting rules cancelled on records: {assessment.conflicting_records}")
    if unverified_count:
        lines.append(
            f"{unverified_count} contributing record(s) are unverified (reliability 0.5) — "
            "none are presented as confirmed."
        )
    if previous is None:
        lines.append("Initial ranking.")
        return lines
    for hyp in sorted(scores, key=lambda h: -(abs(scores[h] - previous.scores.get(h, 0.0)))):
        delta = scores[hyp] - previous.scores.get(hyp, 0.0)
        lines.append(f"{hyp}: {_fmt_delta(previous.scores.get(hyp, 0.0), scores[hyp])}")
        old_groups = previous.groups.get(hyp, {})
        new_groups = groups.get(hyp, {})
        for group in sorted(set(old_groups) | set(new_groups)):
            old_v, new_v = old_groups.get(group, 0.0), new_groups.get(group, 0.0)
            if abs(new_v - old_v) > 1e-9:
                lines.append(f"    {group}: {old_v:+.2f} -> {new_v:+.2f}")
    return lines


@dataclass
class RankResult:
    snapshot: RankingSnapshot
    assessment: Assessment
    raw_scores: Dict[str, float]


def rank(
    ledger: EvidenceLedger,
    pack: DomainPack,
    policy: Policy,
    round_no: int = 0,
    previous: Optional[RankingSnapshot] = None,
) -> RankResult:
    """Produce the evidence-score ranking snapshot for the current ledger state."""
    assessment = assess(ledger, pack)
    if assessment.total_weight < policy.min_total_weight:
        raise InsufficientEvidenceError(
            f"total evidence weight {assessment.total_weight:.2f} < min_total_weight "
            f"{policy.min_total_weight}: INSUFFICIENT_EVIDENCE, no ranking emitted"
        )
    groups, raw = group_strongest(assessment, pack)
    scores = normalise(raw)
    leader = sorted(scores, key=lambda h: (-scores[h], h))[0]
    contributing_ids = sorted({c.record_id for cs in assessment.contributions.values() for c in cs})
    unverified_count = sum(
        1
        for rid in contributing_ids
        if ledger.get(rid) is not None and ledger.get(rid).reliability < 1.0
    )
    explanation = _explanation(scores, groups, assessment, previous, contributing_ids, unverified_count)
    snapshot = RankingSnapshot(
        round=round_no,
        scores=scores,
        leader=leader,
        evidence_ids=contributing_ids,
        status="ranked",
        explanation=explanation,
        groups=groups,
    )
    return RankResult(snapshot=snapshot, assessment=assessment, raw_scores=raw)
