"""Challenger (deterministic rules first, then optional LLM).

`challenge(leader_id, ledger)` receives ONLY the leading hypothesis id and the raw ledger —
never the Investigator's reasoning (enforced by the signature; there is no state or
reasoning parameter). It never states a conclusion and never touches scores.

Step 1 (deterministic, from the pack's relation rules):
- contradictions: raw records whose rule effects CONTRADICT the leader;
- missing evidence: rule-referenced evidence types with no records in the ledger.
Step 2 (only when an online LLM is configured): the LLM may add contradictions/missing
evidence; items citing unknown IDs or stating a conclusion are REJECTED (deterministic gate).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from core.domain import LoadedPack
from core.evidence import EvidenceLedger
from core.llm import LLMClient
from core.scoring import _matches

# Deterministic conclusion gate: any LLM finding whose text asserts a conclusion is rejected.
_CONCLUSION_PHRASES = (
    "therefore",
    "in conclusion",
    "the cause is",
    "was caused by",
    "is guilty",
    "is confirmed",
    "conclusion:",
)


def _is_conclusion(text: str) -> bool:
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in _CONCLUSION_PHRASES)


class Challenger:
    def __init__(self, loaded_pack: LoadedPack, llm: LLMClient | None = None) -> None:
        self.loaded_pack = loaded_pack
        self.llm = llm

    def challenge(self, leader_id: str | None, ledger: EvidenceLedger) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        pack = self.loaded_pack.pack
        contradictions: List[Dict[str, Any]] = []
        missing: List[Dict[str, Any]] = []

        # --- Step 1: deterministic checks from the pack's relation rules -----------------
        for record in ledger.records():
            if not record.evidence_type:
                continue
            for rule in pack.relation_rules:
                if rule.evidence_type != record.evidence_type:
                    continue
                if leader_id and rule.effects.get(leader_id) == "contradicts" and _matches(rule.when, record):
                    contradictions.append(
                        {
                            "ledger_ids": [record.id],
                            "why": (
                                f"{record.id}: '{record.observation}' contradicts '{leader_id}' "
                                f"per pack rule ({rule.evidence_type} {rule.when.op} {rule.when.value!r})"
                            ),
                        }
                    )
        if leader_id is None:
            contradictions = []  # nothing to challenge before the first ranking

        rules_touching_leader = {
            rule.evidence_type
            for rule in pack.relation_rules
            if leader_id is None or leader_id in rule.effects
        }
        present_types = {r.evidence_type for r in ledger.records() if r.evidence_type}
        for et_id in sorted(rules_touching_leader - present_types):
            if pack.evidence_type(et_id) is not None:
                missing.append(
                    {
                        "what": et_id,
                        "why": (
                            f"no '{et_id}' records in the ledger; pack rules would let such a "
                            f"record confirm or refute '{leader_id or 'any hypothesis'}'"
                        ),
                    }
                )

        # --- Step 2: optional LLM findings, validated -----------------------------------
        if self.llm is not None and not self.llm.offline and leader_id:
            raw_items = [
                {"id": r.id, "evidence_type": r.evidence_type, "observation": r.observation}
                for r in ledger.records()
                if r.evidence_type
            ]
            try:
                data = self.llm.complete_structured(
                    f"Leading hypothesis: {leader_id}\nRaw ledger evidence:\n"
                    + "\n".join(f"{i}" for i in raw_items)
                    + '\nReturn JSON {"contradictions": [{"ledger_ids": [..], "why": ".."}], '
                    '"missing_evidence": [{"what": "<evidence_type>", "why": ".."}]}. '
                    "Findings must cite existing ids and must NOT state a conclusion."
                )
            except Exception:
                data = {}
            for item in data.get("contradictions", []):
                ids = list(item.get("ledger_ids", []))
                why = str(item.get("why", "")).strip()
                if not ids or not why or ledger.validate_citations(ids) or _is_conclusion(why):
                    continue  # reject unknown IDs, empty text, or stated conclusions
                contradictions.append({"ledger_ids": ids, "why": f"LLM: {why}"})
            known_types = {et.id for et in pack.evidence_types}
            for item in data.get("missing_evidence", []):
                what = str(item.get("what", "")).strip()
                why = str(item.get("why", "")).strip()
                if not what or what not in known_types or not why or _is_conclusion(why):
                    continue
                if any(m["what"] == what for m in missing):
                    continue
                missing.append({"what": what, "why": f"LLM: {why}"})

        return contradictions, missing
