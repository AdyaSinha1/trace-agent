"""LangGraph driver — drives the SAME workflow phases through a LangGraph StateGraph.

Per docs/state.md: LangGraph is kept only if the state-machine tests pass within the hard
~10-minute wall-clock budget (one quick retry allowed); otherwise the plain-Python machine
in core/workflow.py is the implementation. Either way the plain phases are the logic.
"""

from __future__ import annotations

from typing import Any, Dict, TypedDict

from core.datasource import ScenarioFile
from core.workflow import WorkflowEngine


class _WFState(TypedDict, total=False):
    state: object


def _wrap(fn):
    def node(payload: _WFState) -> Dict[str, Any]:
        fn(payload["state"])
        return {"state": payload["state"]}

    return node


def build_graph(engine: WorkflowEngine):
    from langgraph.graph import END, StateGraph

    graph = StateGraph(_WFState)
    graph.add_node("investigate", _wrap(engine._phase_investigate))
    graph.add_node("challenge", _wrap(engine._phase_challenge))
    graph.add_node("judge", _wrap(engine._phase_judge))
    graph.set_entry_point("investigate")
    graph.add_edge("investigate", "challenge")
    graph.add_edge("challenge", "judge")
    graph.add_conditional_edges(
        "judge",
        lambda payload: (
            END if payload["state"].status.value in {"DONE", "AWAITING_EVIDENCE", "INSUFFICIENT_EVIDENCE"} else "investigate"
        ),
    )
    return graph.compile()


def run_scenario_with_langgraph(engine: WorkflowEngine, scenario: ScenarioFile):
    """One full pass (round 0) through a LangGraph graph; injection still re-invokes."""
    state = engine.run_scenario.__wrapped__ if False else None  # noqa: F841 — build fresh below
    from core.evidence import EvidenceLedger
    from core.state import IncidentState, Status

    fresh = IncidentState(scenario_id=scenario.scenario_id)
    fresh.status = Status.INIT
    from core.datasource import ingest_scenario

    appended = ingest_scenario(scenario, engine.loaded_pack, fresh.ledger)
    fresh.status = Status.INVESTIGATING
    engine._log(fresh, f"INIT -> INVESTIGATING: scenario loaded, {len(appended)} evidence item(s) appended", [r.id for r in appended])
    app = build_graph(engine)
    result = app.invoke({"state": fresh})
    return result["state"]
