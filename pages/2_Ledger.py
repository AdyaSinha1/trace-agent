"""Ledger: append-only entries with IDs, sources, groups, tiers, verification, JSON export."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from ui.common import chrome, load_css, pack, require_state

st.set_page_config(page_title="Ledger", layout="wide")
load_css()
chrome()

st.title("Evidence ledger (append-only)")
state = require_state()
loaded = pack()

rows = []
for record in state.ledger.records():
    et = loaded.pack.evidence_type(record.evidence_type or "")
    rows.append(
        {
            "ID": record.id,
            "kind": record.kind.value,
            "source": record.source,
            "source_group": record.source_group,
            "evidence_type": record.evidence_type or "-",
            "tier": et.tier if et else "-",
            "verified": "verified" if record.reliability >= 1.0 else "unverified",
            "observation": record.observation,
        }
    )
st.markdown(
    f"<div class='trace-counter'>{len(rows)} entries, newest last</div>", unsafe_allow_html=True
)
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=480)
st.caption("RAW observations only. Support/contradict relations come from pack rules, never hand labels.")

st.download_button(
    "Export ledger as JSON",
    data=json.dumps(state.ledger.to_dict(), indent=2),
    file_name=f"{state.scenario_id}_ledger.json",
    mime="application/json",
)
