"""Workflow state models — the contract in docs/state.md, implemented in S7."""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.evidence import EvidenceLedger


class Status(str, Enum):
    INIT = "INIT"
    INVESTIGATING = "INVESTIGATING"
    CHALLENGING = "CHALLENGING"
    JUDGING = "JUDGING"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    DONE = "DONE"
    AWAITING_EVIDENCE = "AWAITING_EVIDENCE"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    ACTION_EXECUTED = "ACTION_EXECUTED"
    REPORTED = "REPORTED"


class Approval(str, Enum):
    NONE = "none"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class HypothesisRef(BaseModel):
    id: str
    label: str
    cited_ids: List[str] = Field(default_factory=list)
    description: str = ""


class Finding(BaseModel):
    """Challenger output: a contradiction or missing evidence. Never a conclusion, never a score."""

    id: str
    kind: str  # "contradiction" | "missing_evidence"
    text: str
    cited_ids: List[str] = Field(default_factory=list)


class RankingSnapshot(BaseModel):
    """Appended on every Judge run; 'why the leader changed' = diff of last two snapshots."""

    round: int
    scores: Dict[str, float]
    leader: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)
    status: str
    explanation: List[str] = Field(default_factory=list)
    groups: Dict[str, Dict[str, float]] = Field(default_factory=dict)  # hyp -> group -> strongest signed weight


class SensitivityResult(BaseModel):
    runs: int
    leader_stability: float
    mean_rank: Dict[str, float]
    top_two_margin: float
    separable: Optional[bool] = None
    label: Optional[str] = None  # "separable" | "not separable"


class NextTestRecommendation(BaseModel):
    best_test: Optional[str] = None
    table: List[Dict[str, object]] = Field(default_factory=list)  # full table incl. margin column
    rationale: str = ""


class AlertDraft(BaseModel):
    """Template-generated from Judge output (no LLM). NEVER sent — a human approves or rejects."""

    text: str
    cited_ids: List[str] = Field(default_factory=list)
    created_at: str
    sent: bool = False  # must never flip to True


class ActionRecord(BaseModel):
    action_id: str
    kind: str  # "work_order" | "notification_draft"
    path: str
    cited_ids: List[str] = Field(default_factory=list)
    approver: str
    timestamp: str


class IncidentState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    scenario_id: str = ""
    round: int = 0  # hard cap: policy.max_rounds
    ledger: EvidenceLedger = Field(default_factory=EvidenceLedger)
    hypotheses: List[HypothesisRef] = Field(default_factory=list)
    leader: Optional[str] = None  # set ONLY by the Judge
    challenger_findings: List[Finding] = Field(default_factory=list)
    ranking_history: List[RankingSnapshot] = Field(default_factory=list)
    sensitivity: Optional[SensitivityResult] = None
    next_test: Optional[NextTestRecommendation] = None
    status: Status = Status.INIT
    alert_draft: Optional[AlertDraft] = None
    approval: Approval = Approval.NONE
    actions: List[ActionRecord] = Field(default_factory=list)
    outcome_report: Optional[str] = None
