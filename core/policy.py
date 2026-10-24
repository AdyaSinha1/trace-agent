"""Engine policy (config/policy.json) — domain-agnostic governance settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field

DEFAULT_POLICY_PATH = Path("config") / "policy.json"


class Policy(BaseModel):
    approval_required_for_actions: bool = True
    max_rounds: int = 2
    separability_cutoff: float = 0.7
    min_total_weight: float = 3.0
    llm_enabled: bool = False
    allowed_actions: List[str] = Field(default_factory=list)
    external_notifications: bool = False  # always false in this project: nothing is ever sent


def load_policy(path: Path | str | None = None) -> Policy:
    policy_path = Path(path) if path else DEFAULT_POLICY_PATH
    if not policy_path.exists():
        return Policy()
    data = json.loads(policy_path.read_text(encoding="utf-8-sig"))  # utf-8-sig: tolerate BOM
    return Policy.model_validate(data)
