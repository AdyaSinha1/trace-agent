"""Agent tests (Investigator, Challenger) with mocked LLMs — no network."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from core.datasource import ingest_scenario, load_scenario
from core.domain import load_pack
from core.evidence import EvidenceLedger
from core.policy import load_policy
from core.state import IncidentState

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "domains" / "water_utility" / "scenarios"


class MockLLM:
    """Configurable fake LLM for agent tests."""

    offline = False
    model_id = "mock-model"

    def __init__(self, structured: Dict[str, Any] | None = None, fail: bool = False) -> None:
        self.structured = structured or {}
        self.fail = fail
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError("mock failure")
        return "mock"

    def complete_structured(self, prompt: str) -> Dict[str, Any]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("mock failure")
        return self.structured


def make_state(scenario_name: str) -> tuple[IncidentState, object]:
    loaded = load_pack(ROOT / "domains" / "water_utility")
    scenario = load_scenario(SCENARIOS / f"{scenario_name}.json")
    state = IncidentState(scenario_id=scenario.scenario_id)
    ingest_scenario(scenario, loaded, state.ledger)
    return state, loaded


def test_investigator_offline_templates() -> None:
    from agents.investigator import Investigator
    from core.llm import TemplateLLMClient

    state, loaded = make_state("clear_factory")
    Investigator(loaded, TemplateLLMClient()).investigate(state)
    assert len(state.hypotheses) == 3
    leader_support = [h for h in state.hypotheses if h.id == "factory_discharge"]
    assert leader_support and leader_support[0].cited_ids  # supporting evidence cited
    claims = state.ledger.records()
    assert any(r.id.endswith("inv:fallback") is False for r in claims)
    for hyp in state.hypotheses:
        assert not state.ledger.validate_citations(hyp.cited_ids)  # all citations resolve


def test_investigator_uses_mocked_llm_and_records_model() -> None:
    from agents.investigator import Investigator

    state, loaded = make_state("clear_factory")
    mock = MockLLM(structured={"interpretation": "Downstream collapse follows the logged release."})
    Investigator(loaded, mock).investigate(state)
    assert mock.calls == 1
    claim = next(r for r in state.ledger.records() if r.id.endswith("inv:hyp:factory_discharge"))
    assert "Downstream collapse" in claim.observation
    assert claim.values["model_id"] == "mock-model"


def test_investigator_falls_back_and_records_on_llm_failure() -> None:
    from agents.investigator import Investigator

    state, loaded = make_state("clear_factory")
    Investigator(loaded, MockLLM(fail=True)).investigate(state)
    fallback = next(r for r in state.ledger.records() if r.id.endswith("inv:fallback"))
    assert "template" in fallback.observation.lower()
    assert len(state.hypotheses) == 3  # template hypotheses still produced


def test_investigator_rejects_unknown_citations() -> None:
    from agents.investigator import Investigator

    state, loaded = make_state("clear_factory")
    # HypothesisRef citations come from assess(); simulate a poisoned pack contribution by
    # asserting the gate directly: unknown cited ids are dropped from the claim record.
    investigator = Investigator(loaded, MockLLM())
    investigator._append_claim(state, "x:inv:t", "claim citing ghost", ["ghost-id", "cf-rep1"], "mock-model")
    record = state.ledger.get("x:inv:t")
    assert "ghost-id" not in record.values["cites"]
    assert "cf-rep1" in record.values["cites"]


def test_challenger_signature_takes_no_investigator_reasoning() -> None:
    import inspect

    from agents.challenger import Challenger

    params = [p for p in inspect.signature(Challenger.challenge).parameters if p != "self"]
    assert params == ["leader_id", "ledger"]  # only the leader + raw ledger


def test_challenger_deterministic_contradictions_and_missing() -> None:
    from agents.challenger import Challenger

    state, loaded = make_state("rainfall_reversal")
    for record in load_scenario(SCENARIOS / "rainfall_reversal.json").injected_evidence:
        state.ledger.append(record)
    challenger = Challenger(loaded, llm=None)  # LLM off
    contradictions, missing = challenger.challenge("factory_discharge", state.ledger)
    ids = {i for c in contradictions for i in c["ledger_ids"]}
    assert "rr-inj1" in ids and "rr-inj5" in ids  # rainfall gauge + lab contradict the leader
    assert any(m["what"] in {"lab_ammonia", "lab_conductivity"} for m in missing)
    assert not state.ledger.validate_citations(list(ids))


def test_challenger_rejects_unknown_ids_and_conclusions() -> None:
    from agents.challenger import Challenger

    state, loaded = make_state("clear_factory")
    mock = MockLLM(
        structured={
            "contradictions": [
                {"ledger_ids": ["ghost-id"], "why": "unknown id item"},
                {"ledger_ids": ["cf-rep1"], "why": "Therefore the factory is guilty"},
                {"ledger_ids": ["cf-rep1"], "why": "cf-rep1 conflicts with the discharge rule"},
            ],
            "missing_evidence": [
                {"what": "not_a_type", "why": "bogus"},
                {"what": "lab_ammonia", "why": "an ammonia test would discriminate"},
            ],
        }
    )
    contradictions, missing = Challenger(loaded, llm=mock).challenge("factory_discharge", state.ledger)
    llm_contr = [c for c in contradictions if c["why"].startswith("LLM:")]
    assert len(llm_contr) == 1  # ghost id + conclusion rejected
    assert all("Therefore" not in c["why"] for c in contradictions)
    assert [m["what"] for m in missing if m["why"].startswith("LLM:")] == []  # deduped: deterministic already found it
    assert sum(1 for m in missing if m["what"] == "lab_ammonia") == 1
    assert all(m["what"] != "not_a_type" for m in missing)  # bogus type rejected


def test_challenger_never_touches_scores() -> None:
    from agents.challenger import Challenger

    state, loaded = make_state("clear_factory")
    before = state.ranking_history, state.leader
    Challenger(loaded, llm=None).challenge("factory_discharge", state.ledger)
    assert (state.ranking_history, state.leader) == before
