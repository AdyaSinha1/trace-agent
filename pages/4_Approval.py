"""Approval: human approves/rejects the draft alert; actions and report; governance section."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from ui.common import ROOT, chrome, load_css, pack, policy, require_state

st.set_page_config(page_title="Approval", layout="wide")
load_css()
chrome()

st.title("Approval, actions and report")
state = require_state()
loaded = pack()
pol = policy()
engine = st.session_state.get("engine")

st.subheader("Draft alert")
if state.alert_draft:
    st.text_area("Template-generated from Judge output (no LLM) — drafts are NEVER sent.",
                 value=state.alert_draft.text, height=190)
else:
    st.write("No draft requested yet.")

col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    approver = st.text_input("Approver name", value="operations")
with col2:
    if st.button("Request draft", disabled=state.status.value != "DONE"):
        try:
            st.session_state.state = engine.request_alert_draft(state)
            st.rerun()
        except Exception as exc:
            st.error(f"Cannot request draft: {exc}")
    can_decide = state.status.value == "AWAITING_APPROVAL" and state.approval.value == "pending"
    if st.button("Approve", disabled=not can_decide):
        st.session_state.state = engine.approve(state, approver=approver or "unnamed")
        st.rerun()
with col3:
    if st.button("Reject", disabled=not can_decide):
        st.session_state.state = engine.reject(state)
        st.rerun()
st.write(f"Status: `{state.status.value}` | Approval: `{state.approval.value}`")

st.subheader("Actions (created only after approval)")
if state.actions:
    for action in state.actions:
        path = Path(action.path)
        if action.kind == "work_order" and path.exists():
            with st.expander(f"Simulated work order {action.action_id} — status 'simulated'"):
                st.json(json.loads(path.read_text(encoding="utf-8")))
        elif action.kind == "notification_draft" and path.exists():
            with st.expander(f"Notification {action.action_id} — DRAFT, NOT SENT"):
                st.code(path.read_text(encoding="utf-8"))
else:
    st.write("No actions. Rejected or pending flows create nothing; nothing is ever sent.")

st.subheader("Outcome report")
if state.outcome_report is None:
    from core.report import build_report

    state.outcome_report = build_report(state, loaded.pack)
st.download_button(
    "Download report (Markdown)",
    data=state.outcome_report,
    file_name=f"{state.scenario_id}_report.md",
    mime="text/markdown",
)
with st.expander("Preview report"):
    st.markdown(state.outcome_report)

st.divider()
st.subheader("Governance")
st.write("**Policy in force (config/policy.json):**")
st.json(
    {
        "approval_required_for_actions": pol.approval_required_for_actions,
        "max_rounds": pol.max_rounds,
        "separability_cutoff": pol.separability_cutoff,
        "min_total_weight": pol.min_total_weight,
        "llm_enabled": pol.llm_enabled,
        "allowed_actions": pol.allowed_actions,
        "external_notifications": pol.external_notifications,
    }
)
st.markdown(
    "**Controls (true to the code):**\n"
    "- Every claim must cite existing ledger IDs; unknown citations are rejected.\n"
    "- Scores are evidence scores, NOT probabilities, produced only by the deterministic Judge.\n"
    "- INSUFFICIENT_EVIDENCE stops the workflow when total weight is below the threshold.\n"
    "- A narrow margin is labelled not separable and never presented as confident.\n"
    "- No action executes unless approval == approved; rejected flows create nothing.\n"
    "- Notifications are drafts marked DRAFT, NOT SENT; nothing is ever sent.\n"
    "- The ledger is append-only; every workflow step is recorded in it.\n"
    "- Offline mode runs with no API key; the LLM never sets or edits a score."
)
