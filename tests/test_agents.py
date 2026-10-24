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
