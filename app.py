"""Trace UI (Streamlit) — Step 1 skeleton. Generic: every label comes from a DomainPack.

Scores are labelled "evidence scores, not probabilities" everywhere; data is simulated;
no source is confirmed. Engine panels land in S4/S8.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from core.domain import discover_packs, load_pack
from core.policy import load_policy

load_dotenv()

st.set_page_config(page_title="Trace", page_icon=None, layout="wide")
st.title("Trace — the investigator that tries to prove itself wrong")
st.caption(
    "Evidence scores, not probabilities. Simulated data. No source is confirmed. "
    "Alert drafts are never sent — a human approves or rejects."
)

policy = load_policy()
pack_dirs = discover_packs()

if not pack_dirs:
    st.error("No domain packs found under domains/ (expected domains/*/pack.json).")
    st.stop()

pack_name = st.sidebar.selectbox(
    "Domain pack", [d.name for d in pack_dirs], format_func=lambda n: n.replace("_", " ")
)
loaded = load_pack(Path("domains") / pack_name)
pack = loaded.pack

st.sidebar.subheader("Policy")
st.sidebar.write(
    {
        "max_rounds": policy.max_rounds,
        "min_total_weight": policy.min_total_weight,
        "separability_cutoff": policy.separability_cutoff,
        "llm_enabled": policy.llm_enabled,
        "external_notifications": policy.external_notifications,
    }
)

col1, col2 = st.columns(2)

with col1:
    st.subheader("Competing hypotheses")
    for h in pack.hypotheses:
        st.markdown(f"- **{h.id}** — {h.label}")

    st.subheader("Candidate tests")
    st.dataframe(
        pd.DataFrame(
            [
                {"id": t.id, "test": t.label, "cost": t.cost, "rationale": t.rationale}
                for t in pack.tests
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

with col2:
    st.subheader("Evidence types (expert priors, not fitted)")
    st.dataframe(
        pd.DataFrame(
            [
                {"id": et.id, "tier": et.tier, "weight": et.weight, "rationale": et.rationale}
                for et in pack.evidence_types
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Relation rules (derived, never hand-labelled)")
    st.write(f"{len(pack.relation_rules)} rules in pack.json")

st.info("Step 1 skeleton: ranking, agents, workflow and reliability panels land in S2+.")
