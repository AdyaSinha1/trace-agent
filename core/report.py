"""Outcome report (S8/S11): Markdown per incident + UI download button.

Contents: ranking history, contradictions with citations, uncertainty and separability,
next test, approvals, actions, limitations.
"""

from __future__ import annotations

from core.domain import DomainPack
from core.state import IncidentState


def build_report(state: IncidentState, pack: DomainPack) -> str:
    raise NotImplementedError("S8")
