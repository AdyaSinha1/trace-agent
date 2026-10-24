"""Workflow, actions, report, CLI tests (offline; no network, no real LLM)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.actions import FileOutboxAdapter, run_approved_actions
from core.datasource import load_scenario
from core.domain import load_pack
from core.evidence import EvidenceLedger
from core.llm import TemplateLLMClient
from core.policy import load_policy
from core.report import build_report
from core.state import Approval, IncidentState, Status
from core.workflow import MAX_STEPS, WorkflowEngine, WorkflowError

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "domains" / "water_utility" / "scenarios"


def make_engine(tmp_path, offline: bool = True) -> tuple[WorkflowEngine, object]:
    loaded = load_pack(ROOT / "domains" / "water_utility")
    policy = load_policy(ROOT / "config" / "policy.json")
    from core.llm import make_llm_client

    llm = make_llm_client(offline=True) if offline else make_llm_client(offline=False)
    engine = WorkflowEngine(loaded, policy, llm=llm, action_adapter=FileOutboxAdapter(tmp_path / "outbox"))
    return engine, loaded


def test_full_offline_rainfall_flow_transitions(tmp_path) -> None:
    engine, loaded = make_engine(tmp_path)
    scenario = load_scenario(SCENARIOS / "rainfall_reversal.json")
    state = engine.run_scenario(scenario)
    assert state.status == Status.AWAITING_EVIDENCE  # round 0: leader not yet stable
    assert state.leader == "factory_discharge"
    assert state.next_test is not None

    engine.inject_evidence(state, list(scenario.injected_evidence), note="ui button")
    assert state.round == 1
    assert state.status == Status.DONE  # leader stable and separable after reversal
    assert state.leader == "storm_runoff"

    engine.request_alert_draft(state)
    assert state.status == Status.AWAITING_APPROVAL
    assert state.approval == Approval.PENDING
    assert "DRAFT ALERT" in state.alert_draft.text
    assert "evidence scores, not probabilities" in state.alert_draft.text.lower()
    assert "no source is confirmed" in state.alert_draft.text.lower()
    assert not state.ledger.validate_citations(state.alert_draft.cited_ids)

    engine.approve(state, approver="test-human")
    assert state.status == Status.REPORTED
    assert state.approval == Approval.APPROVED
    assert {a.kind for a in state.actions} == {"work_order", "notification_draft"}
    assert state.outcome_report and "Incident report" in state.outcome_report
    # every step recorded in the ledger
    assert any(r.id.startswith("rainfall_reversal:wf-") for r in state.ledger.records())


def test_rejected_flow_creates_nothing(tmp_path) -> None:
    engine, loaded = make_engine(tmp_path)
    scenario = load_scenario(SCENARIOS / "rainfall_reversal.json")
    state = engine.run_scenario(scenario)
    engine.inject_evidence(state, list(scenario.injected_evidence))
    engine.request_alert_draft(state)
    outbox = Path(state.actions) if False else tmp_path / "outbox"  # noqa: F841
    engine.reject(state)
    assert state.status == Status.REPORTED
    assert state.approval == Approval.REJECTED
    assert state.actions == []
    assert not (tmp_path / "outbox" / "work_orders").exists() or not list((tmp_path / "outbox" / "work_orders").glob("*.json"))
    assert not (tmp_path / "outbox" / "notifications").exists() or not list((tmp_path / "outbox" / "notifications").glob("*.md"))


def test_no_action_without_approval(tmp_path) -> None:
    engine, loaded = make_engine(tmp_path)
    scenario = load_scenario(SCENARIOS / "rainfall_reversal.json")
    state = engine.run_scenario(scenario)
    engine.inject_evidence(state, list(scenario.injected_evidence))
    engine.request_alert_draft(state)
    state.approval = Approval.NONE  # simulate a bypass attempt
    with pytest.raises(PermissionError):
        run_approved_actions(state, loaded.pack, engine.policy, engine.action_adapter, "attacker")
    engine.approval = state.approval  # keep engine consistent for teardown
    assert not list((tmp_path / "outbox").rglob("wo-*.json"))


def test_max_rounds_cap_and_no_infinite_loop(tmp_path) -> None:
    engine, loaded = make_engine(tmp_path)
    policy = engine.policy
    scenario = load_scenario(SCENARIOS / "clear_factory.json")
    state = engine.run_scenario(scenario)
    # leader stable + separable on round 0? previous is None on first judge -> AWAITING or DONE
    assert state.status in {Status.AWAITING_EVIDENCE, Status.DONE}
    # keep injecting until the cap is reached: no infinite loop, no round beyond max_rounds
    for _ in range(policy.max_rounds + 3):
        if state.round >= policy.max_rounds:
            with pytest.raises(WorkflowError):
                engine.inject_evidence(state, [], note="over-cap")
            break
        engine.inject_evidence(state, [])
    assert state.round <= policy.max_rounds


def test_missing_data_ends_insufficient(tmp_path) -> None:
    engine, loaded = make_engine(tmp_path)
    state = engine.run_scenario(load_scenario(SCENARIOS / "missing_data.json"))
    assert state.status == Status.INSUFFICIENT_EVIDENCE
    assert state.ranking_history == []


def test_scores_only_from_the_judge(tmp_path) -> None:
    engine, loaded = make_engine(tmp_path)
    scenario = load_scenario(SCENARIOS / "rainfall_reversal.json")
    state = engine.run_scenario(scenario)
    engine.inject_evidence(state, list(scenario.injected_evidence))
    # one snapshot per Judge run; leader always equals the latest snapshot's leader
    assert len(state.ranking_history) == 2
    assert state.leader == state.ranking_history[-1].leader
    # injection itself never writes a snapshot
    history = list(state.ranking_history)
    engine.inject_evidence(state, [])
    assert len(state.ranking_history) == len(history) + 1  # only the re-run Judge added one


def test_simulated_test_outcome_injection(tmp_path) -> None:
    engine, loaded = make_engine(tmp_path)
    scenario = load_scenario(SCENARIOS / "rainfall_reversal.json")
    state = engine.run_scenario(scenario)
    engine.inject_test_outcome(state, "sample_storm_drain", "no_industrial_signature")
    assert state.round == 1
    injected = [r for r in state.ledger.records() if r.source == "simulated_test:sample_storm_drain"]
    assert injected and injected[0].evidence_type == "lab_sample"
    assert injected[0].values["value"] == "no_industrial_signature"
    with pytest.raises(WorkflowError):
        engine.inject_test_outcome(state, "not_a_test", "whatever")


def test_report_cites_only_existing_ids(tmp_path) -> None:
    import re

    engine, loaded = make_engine(tmp_path)
    scenario = load_scenario(SCENARIOS / "rainfall_reversal.json")
    state = engine.run_scenario(scenario)
    engine.inject_evidence(state, list(scenario.injected_evidence))
    engine.request_alert_draft(state)
    engine.reject(state)
    report = state.outcome_report
    line = [l for l in report.splitlines() if l.startswith("Cited ledger IDs:")]
    assert line
    ids = [i.strip() for i in line[0].split(":", 1)[1].split(",") if i.strip() and i != "none"]
    assert ids and not state.ledger.validate_citations(ids)


def test_notification_contains_draft_not_sent(tmp_path) -> None:
    engine, loaded = make_engine(tmp_path)
    scenario = load_scenario(SCENARIOS / "rainfall_reversal.json")
    state = engine.run_scenario(scenario)
    engine.inject_evidence(state, list(scenario.injected_evidence))
    engine.request_alert_draft(state)
    engine.approve(state, "human")
    notification = next(a for a in state.actions if a.kind == "notification_draft")
    text = Path(notification.path).read_text(encoding="utf-8")
    assert "DRAFT, NOT SENT" in text
    assert "evidence scores, not probabilities" in text.lower()
    assert "no source is confirmed" in text.lower()


def test_langgraph_driver_matches_plain_engine(tmp_path) -> None:
    """LangGraph attempt: same phases through a StateGraph must give the same result."""
    try:
        from core.langgraph_driver import run_scenario_with_langgraph
    except Exception as exc:  # import or API mismatch
        pytest.skip(f"LangGraph unavailable: {exc}")
    engine, _ = make_engine(tmp_path)
    scenario = load_scenario(SCENARIOS / "rainfall_reversal.json")
    state = run_scenario_with_langgraph(engine, scenario)
    plain, _ = make_engine(tmp_path / "plain")
    expected = plain.run_scenario(scenario)
    assert state.status == expected.status
    assert state.leader == expected.leader
    assert {k: round(v, 6) for k, v in state.ranking_history[-1].scores.items()} == {
        k: round(v, 6) for k, v in expected.ranking_history[-1].scores.items()
    }
