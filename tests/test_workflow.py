"""Workflow, actions, report, CLI tests (offline; no network, no real LLM).

Round flow (max_rounds=2): round 0 always ends AWAITING_EVIDENCE (no previous snapshot, so
the leader cannot be "stable" yet). A round where the leader CHANGED also ends
AWAITING_EVIDENCE (that is the demo). DONE arrives when leader is stable AND separable, or
at the round cap (round >= max_rounds).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.actions import FileOutboxAdapter, run_approved_actions
from core.datasource import load_scenario
from core.domain import load_pack
from core.llm import make_llm_client
from core.policy import load_policy
from core.report import build_report
from core.state import Approval, IncidentState, Status
from core.workflow import WorkflowEngine, WorkflowError

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "domains" / "water_utility" / "scenarios"


def make_engine(tmp_path) -> tuple[WorkflowEngine, object]:
    loaded = load_pack(ROOT / "domains" / "water_utility")
    policy = load_policy(ROOT / "config" / "policy.json")
    engine = WorkflowEngine(
        loaded, policy, llm=make_llm_client(offline=True), action_adapter=FileOutboxAdapter(tmp_path / "outbox")
    )
    return engine, loaded


def rainfall_state(tmp_path):
    engine, loaded = make_engine(tmp_path)
    scenario = load_scenario(SCENARIOS / "rainfall_reversal.json")
    state = engine.run_scenario(scenario)
    return engine, loaded, scenario, state


def rainfall_to_done(tmp_path):
    """Round 0 -> inject real evidence (leader flips) -> inject more (round cap) -> DONE."""
    engine, loaded, scenario, state = rainfall_state(tmp_path)
    engine.inject_evidence(state, list(scenario.injected_evidence), note="ui button")
    engine.inject_evidence(state, [], note="round cap filler")
    assert state.status == Status.DONE
    return engine, loaded, scenario, state


def test_full_offline_rainfall_flow_transitions(tmp_path) -> None:
    engine, loaded, scenario, state = rainfall_state(tmp_path)
    assert state.status == Status.AWAITING_EVIDENCE  # round 0: leader cannot be stable yet
    assert state.leader == "factory_discharge"
    assert state.next_test is not None

    engine.inject_evidence(state, list(scenario.injected_evidence), note="ui button")
    assert state.round == 1
    assert state.leader == "storm_runoff"  # the demo reversal happened...
    assert state.status == Status.AWAITING_EVIDENCE  # ...but a changed leader is not "stable"

    engine.inject_evidence(state, [], note="round cap")
    assert state.round == 2 and state.status == Status.DONE  # round cap -> DONE

    engine.request_alert_draft(state)
    assert state.status == Status.AWAITING_APPROVAL and state.approval == Approval.PENDING
    assert "DRAFT ALERT" in state.alert_draft.text
    assert "evidence scores, not probabilities" in state.alert_draft.text.lower()
    assert "no source is confirmed" in state.alert_draft.text.lower()
    assert not state.ledger.validate_citations(state.alert_draft.cited_ids)

    engine.approve(state, approver="test-human")
    assert state.status == Status.REPORTED
    assert {a.kind for a in state.actions} == {"work_order", "notification_draft"}
    assert state.outcome_report and "Incident report" in state.outcome_report
    assert any(r.id.startswith("rainfall_reversal:wf-") for r in state.ledger.records())


def test_leader_change_is_visible_in_snapshot_diff(tmp_path) -> None:
    engine, loaded, scenario, state = rainfall_state(tmp_path)
    engine.inject_evidence(state, list(scenario.injected_evidence))
    diff_lines = state.ranking_history[-1].explanation
    assert any("rainfall_gauge" in line or "upstream_chain" in line for line in diff_lines)


def test_rejected_flow_creates_nothing(tmp_path) -> None:
    engine, loaded, scenario, state = rainfall_to_done(tmp_path)
    engine.request_alert_draft(state)
    engine.reject(state)
    assert state.status == Status.REPORTED
    assert state.approval == Approval.REJECTED
    assert state.actions == []
    work_orders = list((tmp_path / "outbox" / "work_orders").glob("*.json")) if (tmp_path / "outbox" / "work_orders").exists() else []
    notifications = list((tmp_path / "outbox" / "notifications").glob("*.md")) if (tmp_path / "outbox" / "notifications").exists() else []
    assert work_orders == [] and notifications == []


def test_no_action_without_approval(tmp_path) -> None:
    engine, loaded, scenario, state = rainfall_to_done(tmp_path)
    engine.request_alert_draft(state)
    state.approval = Approval.NONE  # simulate a bypass attempt
    with pytest.raises(PermissionError):
        run_approved_actions(state, loaded.pack, engine.policy, engine.action_adapter, "attacker")
    assert not list((tmp_path / "outbox").rglob("wo-*.json"))


def test_max_rounds_cap_and_no_infinite_loop(tmp_path) -> None:
    engine, loaded = make_engine(tmp_path)
    policy = engine.policy
    scenario = load_scenario(SCENARIOS / "clear_factory.json")
    state = engine.run_scenario(scenario)
    assert state.status in {Status.AWAITING_EVIDENCE, Status.DONE}
    for _ in range(policy.max_rounds + 3):
        if state.round >= policy.max_rounds:
            with pytest.raises(WorkflowError):
                engine.inject_evidence(state, [], note="over-cap")
            break
        engine.inject_evidence(state, [])
    assert state.round <= policy.max_rounds  # never exceeds the cap; always terminates


def test_missing_data_ends_insufficient(tmp_path) -> None:
    engine, loaded = make_engine(tmp_path)
    state = engine.run_scenario(load_scenario(SCENARIOS / "missing_data.json"))
    assert state.status == Status.INSUFFICIENT_EVIDENCE
    assert state.ranking_history == []


def test_scores_only_from_the_judge(tmp_path) -> None:
    engine, loaded, scenario, state = rainfall_state(tmp_path)
    assert len(state.ranking_history) == 1
    engine.inject_evidence(state, list(scenario.injected_evidence))
    assert len(state.ranking_history) == 2  # exactly one snapshot per Judge run
    assert state.leader == state.ranking_history[-1].leader
    engine.inject_evidence(state, [])
    assert len(state.ranking_history) == 3


def test_simulated_test_outcome_injection(tmp_path) -> None:
    engine, loaded, scenario, state = rainfall_state(tmp_path)
    engine.inject_test_outcome(state, "sample_storm_drain", "no_industrial_signature")
    assert state.round == 1
    injected = [r for r in state.ledger.records() if r.source == "simulated_test:sample_storm_drain"]
    assert injected and injected[0].evidence_type == "lab_sample"
    assert injected[0].values["value"] == "no_industrial_signature"
    with pytest.raises(WorkflowError):
        engine.inject_test_outcome(state, "not_a_test", "whatever")


def test_report_cites_only_existing_ids(tmp_path) -> None:
    engine, loaded, scenario, state = rainfall_to_done(tmp_path)
    engine.request_alert_draft(state)
    engine.reject(state)
    report = state.outcome_report
    assert report and "Incident report" in report
    line = [l for l in report.splitlines() if l.startswith("Cited ledger IDs:")]
    assert line
    ids = [i.strip() for i in line[0].split(":", 1)[1].split(",") if i.strip() and i != "none"]
    assert ids and not state.ledger.validate_citations(ids)


def test_notification_contains_draft_not_sent(tmp_path) -> None:
    engine, loaded, scenario, state = rainfall_to_done(tmp_path)
    engine.request_alert_draft(state)
    engine.approve(state, "human")
    notification = next(a for a in state.actions if a.kind == "notification_draft")
    text = Path(notification.path).read_text(encoding="utf-8")
    assert "DRAFT, NOT SENT" in text
    assert "evidence scores, not probabilities" in text.lower()
    assert "no source is confirmed" in text.lower()
    work_order = next(a for a in state.actions if a.kind == "work_order")
    import json

    wo = json.loads(Path(work_order.path).read_text(encoding="utf-8"))
    assert wo["status"] == "simulated" and wo["approver"] == "human"


def test_langgraph_driver_matches_plain_engine(tmp_path) -> None:
    """LangGraph attempt: same phases through a StateGraph must give the same result."""
    try:
        from core.langgraph_driver import run_scenario_with_langgraph
    except Exception as exc:  # import or API mismatch
        pytest.skip(f"LangGraph unavailable: {exc}")
    engine, loaded, scenario, _ = rainfall_state(tmp_path)
    state = run_scenario_with_langgraph(engine, scenario)
    plain, _ = make_engine(tmp_path / "plain")
    expected = plain.run_scenario(scenario)
    assert state.status == expected.status
    assert state.leader == expected.leader
    assert {k: round(v, 6) for k, v in state.ranking_history[-1].scores.items()} == {
        k: round(v, 6) for k, v in expected.ranking_history[-1].scores.items()
    }
