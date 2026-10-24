"""Incident workflow / state machine (docs/state.md).

INIT -> INVESTIGATING -> CHALLENGING -> JUDGING -> INSUFFICIENT_EVIDENCE | DONE |
AWAITING_EVIDENCE; AWAITING_EVIDENCE -> INVESTIGATING on injected evidence (round + 1,
max_rounds from policy); DONE -> AWAITING_APPROVAL -> ACTION_EXECUTED -> REPORTED
(rejected -> REPORTED with no actions). Every step is recorded in the append-only ledger.
A hard loop guard (MAX_STEPS) makes an infinite loop impossible.

The phases are plain-Python methods; core.langgraph_driver can drive the SAME methods
through a LangGraph StateGraph (decision recorded in docs/state.md).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, List, Optional

from agents.challenger import Challenger
from agents.investigator import Investigator
from agents.judge import Judge
from core.datasource import ScenarioFile, ingest_scenario
from core.domain import LoadedPack
from core.evidence import EvidenceKind, EvidenceRecord
from core.llm import LLMClient, TemplateLLMClient
from core.policy import Policy
from core.state import ActionRecord, AlertDraft, Approval, Finding, IncidentState, Status

MAX_STEPS = 50  # hard loop guard: the machine can never cycle forever


class WorkflowError(RuntimeError):
    """User-facing workflow violation (e.g. max rounds reached, approval missing)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class WorkflowEngine:
    def __init__(
        self,
        loaded_pack: LoadedPack,
        policy: Policy,
        llm: Optional[LLMClient] = None,
        action_adapter=None,
    ) -> None:
        self.loaded_pack = loaded_pack
        self.policy = policy
        llm = llm if llm is not None else TemplateLLMClient()
        self.llm = llm
        online = (llm is not None) and (not llm.offline) and policy.llm_enabled
        self.investigator = Investigator(loaded_pack, llm if online else TemplateLLMClient())
        self.challenger = Challenger(loaded_pack, llm=llm if online else None)
        self.judge = Judge(loaded_pack, policy)
        self.action_adapter = action_adapter

    # ------------------------------------------------------------------ helpers
    def _next_id(self, state: IncidentState, prefix: str) -> str:
        n = 1
        while f"{prefix}-{n}" in state.ledger.ids():
            n += 1
        return f"{prefix}-{n}"

    def _log(self, state: IncidentState, text: str, cited_ids: Iterable[str]) -> None:
        record_id = self._next_id(state, f"{state.scenario_id}:wf")
        valid = [cid for cid in cited_ids if not state.ledger.validate_citations([cid])]
        state.ledger.append(
            EvidenceRecord(
                id=record_id,
                source="workflow",
                source_group="workflow_log",
                timestamp=_now(),
                location="engine",
                observation=text,
                kind=EvidenceKind.TOOL_OUTPUT,
                reliability=1.0,
                values={"cites": valid},
            )
        )

    # ------------------------------------------------------------------ phases
    def _phase_investigate(self, state: IncidentState) -> None:
        self.investigator.investigate(state)
        state.status = Status.CHALLENGING
        claim_ids = [r.id for r in state.ledger.records() if r.id.startswith(f"{state.scenario_id}:inv:")]
        self._log(state, f"INVESTIGATING -> CHALLENGING: investigator proposed {len(state.hypotheses)} hypotheses", claim_ids)

    def _phase_challenge(self, state: IncidentState) -> None:
        contradictions, missing = self.challenger.challenge(state.leader, state.ledger)
        findings: List[Finding] = []
        for i, c in enumerate(contradictions):
            findings.append(Finding(id=f"{state.scenario_id}:chl:c{i}", kind="contradiction", text=c["why"], cited_ids=c["ledger_ids"]))
        for i, m in enumerate(missing):
            findings.append(Finding(id=f"{state.scenario_id}:chl:m{i}", kind="missing_evidence", text=f"missing {m['what']}: {m['why']}", cited_ids=[]))
        state.challenger_findings = findings
        state.status = Status.JUDGING
        self._log(state, f"CHALLENGING -> JUDGING: {len(contradictions)} contradiction(s), {len(missing)} missing-evidence item(s)", [])

    def _phase_judge(self, state: IncidentState) -> None:
        previous = state.ranking_history[-1] if state.ranking_history else None
        self.judge.run(state)
        if state.status == Status.INSUFFICIENT_EVIDENCE:
            self._log(state, "JUDGING -> INSUFFICIENT_EVIDENCE: total weight below threshold, no ranking emitted", [])
            return
        self.judge.assess_uncertainty(state)
        self.judge.choose_next_test(state)
        snapshot = state.ranking_history[-1]
        leader_stable = previous is not None and previous.leader == snapshot.leader
        if (leader_stable and state.sensitivity is not None and state.sensitivity.separable) or state.round >= self.policy.max_rounds:
            state.status = Status.DONE
            reason = "leader stable and separable" if leader_stable else f"round cap {self.policy.max_rounds} reached"
            self._log(state, f"JUDGING -> DONE ({reason})", snapshot.evidence_ids)
        else:
            state.status = Status.AWAITING_EVIDENCE
            self._log(state, "JUDGING -> AWAITING_EVIDENCE: next test shown", snapshot.evidence_ids)

    def _cycle(self, state: IncidentState) -> None:
        steps = 0
        while state.status in (Status.INVESTIGATING, Status.CHALLENGING, Status.JUDGING):
            steps += 1
            if steps > MAX_STEPS:
                raise WorkflowError("loop guard tripped: workflow did not terminate")
            if state.status == Status.INVESTIGATING:
                self._phase_investigate(state)
            elif state.status == Status.CHALLENGING:
                self._phase_challenge(state)
            else:
                self._phase_judge(state)

    # ------------------------------------------------------------------ public API
    def run_scenario(self, scenario: ScenarioFile) -> IncidentState:
        state = IncidentState(scenario_id=scenario.scenario_id)
        state.status = Status.INIT
        appended = ingest_scenario(scenario, self.loaded_pack, state.ledger)
        state.status = Status.INVESTIGATING
        self._log(state, f"INIT -> INVESTIGATING: scenario loaded, {len(appended)} evidence item(s) appended", [r.id for r in appended])
        self._cycle(state)
        return state

    def inject_evidence(self, state: IncidentState, records: List[EvidenceRecord], note: str = "") -> IncidentState:
        if state.round >= self.policy.max_rounds:
            raise WorkflowError(f"max_rounds={self.policy.max_rounds} reached; cannot inject more evidence")
        appended: List[EvidenceRecord] = []
        for record in records:
            injected = record.model_copy(update={"kind": EvidenceKind.INJECTED})
            state.ledger.append(injected)
            appended.append(injected)
        state.round += 1
        state.status = Status.INVESTIGATING
        self._log(state, f"evidence injected ({note or 'manual'}); round -> {state.round}", [r.id for r in appended])
        self._cycle(state)
        return state

    def inject_test_outcome(self, state: IncidentState, test_id: str, outcome: str) -> IncidentState:
        """Simulated test result -> ledger evidence -> re-run (round + 1, within max_rounds)."""
        test = next((t for t in self.loaded_pack.pack.tests if t.id == test_id), None)
        if test is None:
            raise WorkflowError(f"unknown test {test_id!r}")
        value = test.outcome_values.get(outcome)
        record = EvidenceRecord(
            id=f"{state.scenario_id}:test:{test_id}:{state.round + 1}",
            source=f"simulated_test:{test_id}",
            source_group=f"test:{test_id}",
            timestamp=_now(),
            location="simulated",
            observation=f"simulated outcome '{outcome}' for test '{test_id}'",
            kind=EvidenceKind.TOOL_OUTPUT,
            reliability=1.0,
            evidence_type=test.evidence_type or None,
            values={"value": value} if value is not None else {},
        )
        return self.inject_evidence(state, [record], note=f"simulated test outcome {test_id}={outcome}")

    def inject_work_order_result(self, state: IncidentState, test_id: str, outcome: str) -> IncidentState:
        """ACTION_EXECUTED/REPORTED -> INVESTIGATING (optional), subject to the round cap."""
        if state.round >= self.policy.max_rounds:
            self._log(state, f"work-order result for {test_id} recorded but round cap reached; workflow stays terminal", [])
            return state
        return self.inject_test_outcome(state, test_id, outcome)

    def request_alert_draft(self, state: IncidentState) -> IncidentState:
        if state.status != Status.DONE:
            raise WorkflowError(f"alert draft requires DONE, got {state.status}")
        if state.approval != Approval.NONE:
            raise WorkflowError("an approval decision already exists")
        snapshot = state.ranking_history[-1]
        leader_label = self.loaded_pack.pack.hypothesis_label(snapshot.leader or "")
        supporting = next((h.cited_ids for h in state.hypotheses if h.id == snapshot.leader), []) or snapshot.evidence_ids[:5]
        scores = ", ".join(f"{h}={s:.0f}" for h, s in sorted(snapshot.scores.items(), key=lambda kv: -kv[1]))
        sensitivity = state.sensitivity
        text = (
            "DRAFT ALERT - NOT SENT (a human must approve or reject; nothing is ever sent)\n"
            f"Incident: {state.scenario_id}. Leading hypothesis: {leader_label}.\n"
            f"Evidence scores, not probabilities: {scores}.\n"
            f"Data is simulated; no source is confirmed.\n"
            + (
                f"Uncertainty: {sensitivity.label} (leader stays leader in {sensitivity.leader_stability:.0%} "
                f"of {sensitivity.runs} seeded runs; mean top-two margin {sensitivity.top_two_margin:.1f}).\n"
                if sensitivity else ""
            )
            + f"Cited evidence: {', '.join(supporting) if supporting else 'none'}."
        )
        state.alert_draft = AlertDraft(text=text, cited_ids=supporting, created_at=_now())
        state.approval = Approval.PENDING
        state.status = Status.AWAITING_APPROVAL
        self._log(state, "DONE -> AWAITING_APPROVAL: alert draft generated (template, no LLM)", supporting)
        return state

    def approve(self, state: IncidentState, approver: str) -> IncidentState:
        if state.status != Status.AWAITING_APPROVAL or state.approval != Approval.PENDING:
            raise WorkflowError("approve requires a pending draft in AWAITING_APPROVAL")
        state.approval = Approval.APPROVED
        from core.actions import run_approved_actions  # deterministic tool, never an agent

        state.actions = run_approved_actions(state, self.loaded_pack.pack, self.policy, self.action_adapter, approver)
        state.status = Status.ACTION_EXECUTED
        self._log(state, f"AWAITING_APPROVAL -> ACTION_EXECUTED: {len(state.actions)} simulated action(s) created by {approver}", [a.cited_ids for a in state.actions] and [i for a in state.actions for i in a.cited_ids][:8])
        from core.report import build_report

        state.outcome_report = build_report(state, self.loaded_pack.pack)
        state.status = Status.REPORTED
        self._log(state, "ACTION_EXECUTED -> REPORTED: outcome report generated", [])
        return state

    def reject(self, state: IncidentState) -> IncidentState:
        if state.status != Status.AWAITING_APPROVAL:
            raise WorkflowError("reject requires AWAITING_APPROVAL")
        state.approval = Approval.REJECTED
        state.status = Status.REPORTED  # no actions are created
        self._log(state, "AWAITING_APPROVAL -> REPORTED (rejected): no actions executed", [])
        from core.report import build_report

        state.outcome_report = build_report(state, self.loaded_pack.pack)
        return state
