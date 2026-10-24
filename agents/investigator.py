"""Investigator (LLM + deterministic Python tools).

Reads records, runs deterministic anomaly detection (records that match pack relation
rules), and proposes the pack's hypotheses with supporting ledger IDs. The LLM may ONLY
write interpretation text; numbers and citations stay in Python. Output citing unknown IDs
is rejected. On LLM failure the templates are used and the fallback is recorded in the
ledger.
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.domain import LoadedPack
from core.evidence import EvidenceKind, EvidenceRecord
from core.llm import LLMClient
from core.scoring import assess
from core.state import HypothesisRef, IncidentState


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Investigator:
    def __init__(self, loaded_pack: LoadedPack, llm: LLMClient) -> None:
        self.loaded_pack = loaded_pack
        self.llm = llm

    def _append_claim(
        self, state: IncidentState, record_id: str, text: str, cited_ids: list[str], model_note: str
    ) -> None:
        ledger = state.ledger
        # Citation gate: reject (drop) any cited id that does not exist in the ledger.
        valid_ids = [cid for cid in cited_ids if not ledger.validate_citations([cid])]
        ledger.append(
            EvidenceRecord(
                id=record_id,
                source="investigator",
                source_group="agent_claim",
                timestamp=_now(),
                location="engine",
                observation=text,
                kind=EvidenceKind.AGENT_CLAIM,
                reliability=0.5,
                values={"cites": valid_ids, "model_id": model_note},
            )
        )

    def investigate(self, state: IncidentState) -> IncidentState:
        pack = self.loaded_pack.pack
        ledger = state.ledger
        assessment = assess(ledger, pack)

        supporting = {
            h: sorted({c.record_id for c in cs if c.signed_weight > 0})
            for h, cs in assessment.contributions.items()
        }
        anomaly_ids = sorted({c.record_id for cs in assessment.contributions.values() for c in cs})

        llm_interpretation = None
        fallback_used = False
        if not self.llm.offline:
            summaries = [f"{r.id} [{r.evidence_type}] {r.observation}" for r in ledger.records()[:20]]
            try:
                data = self.llm.complete_structured(
                    "You are a water-incident investigator. Raw evidence items:\n"
                    + "\n".join(summaries)
                    + '\nReturn JSON {"interpretation": "<=80 words; you may cite item ids like cf-rep1; '
                    'do NOT state a final conclusion"}'
                )
                llm_interpretation = str(data.get("interpretation", "")).strip()[:600] or None
            except Exception:
                llm_interpretation = None
                fallback_used = True

        claim_ids: list[str] = []
        hypotheses: list[HypothesisRef] = []
        for hyp in pack.hypotheses:
            ids = supporting.get(hyp.id, [])
            description = (
                f"{hyp.label}: {len(ids)} supporting ledger item(s). "
                "Evidence scores, not probabilities."
            )
            if llm_interpretation:
                description += f" Interpretation: {llm_interpretation}"
            claim_id = f"{state.scenario_id}:inv:r{state.round}:hyp:{hyp.id}"
            self._append_claim(state, claim_id, description, ids, self.llm.model_id)
            claim_ids.append(claim_id)
            hypotheses.append(HypothesisRef(id=hyp.id, label=hyp.label, cited_ids=ids, description=description))

        if anomaly_ids:
            claim_id = f"{state.scenario_id}:inv:r{state.round}:anomalies"
            self._append_claim(
                state,
                claim_id,
                f"Deterministic anomaly detection: {len(anomaly_ids)} record(s) match pack relation "
                "rules (threshold/condition breaches from the domain pack).",
                anomaly_ids,
                "python-deterministic",
            )
            claim_ids.append(claim_id)

        if fallback_used:
            self._append_claim(
                state,
                f"{state.scenario_id}:inv:r{state.round}:fallback",
                "LLM call failed; template hypotheses and deterministic anomaly detection used instead.",
                claim_ids,
                "offline-templates",
            )

        state.hypotheses = hypotheses
        return state
