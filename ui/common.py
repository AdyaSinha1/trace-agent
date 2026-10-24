"""Shared UI helpers: session state, offline workflow runs, theme, stamp and footer."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = ROOT / "domains" / "water_utility"
STAMP = '<div class="trace-stamp">SIMULATED DATA</div>'
FOOTER = (
    '<div class="trace-footer">Offline mode / Data: simulated / '
    "Scores are evidence scores, not probabilities</div>"
)


def load_css() -> None:
    css = (Path(__file__).parent / "theme.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def chrome() -> None:
    """Stamp + footer on every page."""
    st.markdown(STAMP + FOOTER, unsafe_allow_html=True)


def policy():
    from core.policy import load_policy

    if "policy" not in st.session_state:
        st.session_state.policy = load_policy(ROOT / "config" / "policy.json")
    return st.session_state.policy


def pack():
    from core.domain import load_pack

    if "loaded" not in st.session_state:
        st.session_state.loaded = load_pack(PACK_DIR)
    return st.session_state.loaded


def scenarios() -> list[str]:
    return sorted(p.stem for p in (PACK_DIR / "scenarios").glob("*.json"))


def open_investigation(scenario_id: str):
    """Run the workflow OFFLINE (template LLM, deterministic rules) and cache the state."""
    from core.actions import FileOutboxAdapter
    from core.datasource import load_scenario
    from core.llm import make_llm_client
    from core.workflow import WorkflowEngine

    loaded = pack()
    engine = WorkflowEngine(
        loaded,
        policy(),
        llm=make_llm_client(offline=True),
        action_adapter=FileOutboxAdapter(ROOT / "outbox"),
    )
    scenario = load_scenario(PACK_DIR / "scenarios" / f"{scenario_id}.json")
    state = engine.run_scenario(scenario)
    st.session_state.engine = engine
    st.session_state.state = state
    st.session_state.scenario = scenario
    return state


def inject_from_scenario() -> None:
    """Inject the scenario's injected evidence; add a round-cap filler only if needed."""
    engine = st.session_state.engine
    state = st.session_state.state
    scenario = st.session_state.scenario
    if state.round < engine.policy.max_rounds and scenario.injected_evidence:
        st.session_state.state = engine.inject_evidence(state, list(scenario.injected_evidence), note="ui button")
    elif st.session_state.state.round < engine.policy.max_rounds:
        st.session_state.state = engine.inject_evidence(state, [], note="ui filler")


def require_state():
    state = st.session_state.get("state")
    if state is None:
        st.warning("Open an investigation on the Case Desk first.")
        st.stop()
    return state
