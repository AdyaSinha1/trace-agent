"""Trace UI (Streamlit) — Case Desk: open an investigation offline. All labels come from the pack."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from ui.common import chrome, load_css, open_investigation, pack, policy, scenarios

st.set_page_config(page_title="Trace", layout="wide")
load_css()
chrome()

st.title("Trace — Case Desk")
st.caption("The investigator that tries to prove itself wrong. Offline by default: "
           "template hypotheses, deterministic Challenger rules, no API key needed.")

loaded = pack()
pol = policy()
names = scenarios()

col1, col2 = st.columns([2, 1])
with col1:
    scenario_id = st.selectbox("Scenario", names, index=names.index("rainfall_reversal") if "rainfall_reversal" in names else 0)
with col2:
    st.write("")  # alignment
    if st.button("Open investigation", use_container_width=True):
        state = open_investigation(scenario_id)
        st.success(f"Opened {scenario_id}: status {state.status.value}, round {state.round}")

state = st.session_state.get("state")
if state is not None:
    st.subheader("Current case")
    snapshot = state.ranking_history[-1] if state.ranking_history else None
    if snapshot:
        ranked = ", ".join(f"{loaded.pack.hypothesis_label(h)}: {s:.0f}" for h, s in sorted(snapshot.scores.items(), key=lambda kv: -kv[1]))
        st.markdown(f"**Leader:** {loaded.pack.hypothesis_label(state.leader or 'n/a')}  \n"
                    f"**Evidence scores, not probabilities:** {ranked}")
    else:
        st.info("No ranking emitted (INSUFFICIENT_EVIDENCE).")
    st.write(f"Status: `{state.status.value}` | Round: {state.round} of {pol.max_rounds}")

st.divider()
st.subheader("Domain pack")
st.write(f"**{loaded.pack.name}** — {loaded.pack.description}")
st.dataframe(
    pd.DataFrame([{"hypothesis": h.id, "label": h.label} for h in loaded.pack.hypotheses]),
    use_container_width=True, hide_index=True,
)
st.dataframe(
    pd.DataFrame([{"evidence type": et.id, "tier": et.tier, "weight": et.weight, "rationale": et.rationale}
                  for et in loaded.pack.evidence_types]),
    use_container_width=True, hide_index=True,
)
st.caption("Weights are expert-assigned priors (ACH practice), not fitted to data.")
