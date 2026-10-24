"""Challenge + Next test: Challenger findings with citations, missing evidence, next-test table."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.common import chrome, load_css, pack, require_state

st.set_page_config(page_title="Challenge + Next test", layout="wide")
load_css()
chrome()

st.title("Challenger findings and next test")
state = require_state()
loaded = pack()

st.subheader("Challenger findings (leader challenged against raw evidence)")
contradictions = [f for f in state.challenger_findings if f.kind == "contradiction"]
missing = [f for f in state.challenger_findings if f.kind == "missing_evidence"]
if contradictions:
    for finding in contradictions:
        cites = ", ".join(f"`{i}`" for i in finding.cited_ids) or "no citation"
        st.markdown(f"<div class='trace-contradiction'>{finding.text} (cites: {cites})</div>",
                    unsafe_allow_html=True)
else:
    st.write("No contradictions found against the current leader.")
st.subheader("Missing evidence")
for finding in missing:
    st.markdown(f"- {finding.text}")
if not missing:
    st.write("None flagged.")

st.divider()
st.subheader("Next test (heuristic ranking, not exact optimisation)")
if state.next_test and state.next_test.best_test:
    rows = []
    for row in state.next_test.table:
        rows.append(
            {
                "test": row["test_id"],
                "cost": row["cost"],
                "expected info gain": row["expected_info_gain"],
                "expected margin change": row["expected_margin_change"],
                "gain per cost": row["gain_per_cost"],
                "best": "<-- BEST" if row["test_id"] == state.next_test.best_test else "",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(state.next_test.rationale)
    st.write("**What each possible result would imply** (from the pack config):")
    best_row = next(r for r in state.next_test.table if r["test_id"] == state.next_test.best_test)
    for implication in best_row["implications"]:
        st.markdown(f"- {implication}")
else:
    st.write("No next test available.")
