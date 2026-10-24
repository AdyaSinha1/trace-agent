"""Board: ranked evidence scores, uncertainty warning, why-the-leader-changed, injection."""
from __future__ import annotations

import streamlit as st

from ui.common import chrome, inject_from_scenario, load_css, pack, require_state

st.set_page_config(page_title="Board", layout="wide")
load_css()
chrome()

st.title("Board")
state = require_state()
loaded = pack()

if not state.ranking_history:
    st.warning("No ranking emitted (INSUFFICIENT_EVIDENCE) — total evidence weight is below the threshold.")
    st.stop()

snapshot = state.ranking_history[-1]
st.subheader("Evidence scores, not probabilities")
leader = snapshot.leader
for hyp in loaded.pack.hypotheses:
    score = snapshot.scores.get(hyp.id, 0.0)
    label = f"{hyp.label} — LEADER" if hyp.id == leader else hyp.label
    css = "trace-leader" if hyp.id == leader else ""
    st.markdown(f'<div class="{css}"><strong>{label}</strong> — {score:.0f}</div>', unsafe_allow_html=True)
    st.progress(min(score / 100.0, 1.0))
st.caption("Normalised to 100 across the pack's hypotheses. Weights are expert priors, not fitted.")

if state.sensitivity and not state.sensitivity.separable:
    st.error(
        f"Uncertainty warning: NOT SEPARABLE — leader stays leader in only "
        f"{state.sensitivity.leader_stability:.0%} of {state.sensitivity.runs} seeded runs "
        f"(cut-off {state.sensitivity.top_two_margin:.1f} mean top-two margin). "
        "A narrow margin must not be read as a confident attribution."
    )
elif state.sensitivity:
    st.success(
        f"Separable: leader stays leader in {state.sensitivity.leader_stability:.0%} of "
        f"{state.sensitivity.runs} seeded runs (mean top-two margin {state.sensitivity.top_two_margin:.1f})."
    )

st.subheader("Why the leader changed")
previous = state.ranking_history[-2] if len(state.ranking_history) >= 2 else None
if previous is None:
    st.write("Initial ranking (no previous snapshot).")
else:
    for line in snapshot.explanation:
        st.markdown(f"- {line}")
    st.caption(f"Evidence IDs in the diff come from the snapshots; run {len(state.ranking_history)} of the Judge.")

st.subheader(f"State: {state.status.value} | Round: {state.round}")
max_rounds = st.session_state.engine.policy.max_rounds if st.session_state.get("engine") else 2
if st.button("Inject new evidence", disabled=state.round >= max_rounds):
    inject_from_scenario()
    st.rerun()
if state.round >= max_rounds:
    st.caption(f"Round cap {max_rounds} reached — no further injections.")
