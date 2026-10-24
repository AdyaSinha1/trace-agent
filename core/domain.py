"""DomainPack schema + loader — the ONLY place domain content enters the engine.

A pack (domains/<name>/pack.json) declares: hypotheses, evidence types (tier, weight,
rationale), relation rules, candidate tests, action templates and thresholds. A pack may
also register pure-Python feature extractors in features.py (raw readings -> evidence items).
core/ contains no water-specific (or any domain-specific) logic.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Effect = Literal["supports", "contradicts"]
Tier = Literal["A", "B", "C"]
Op = Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains"]


class Hypothesis(BaseModel):
    id: str
    label: str


class EvidenceType(BaseModel):
    id: str
    tier: Tier
    weight: float
    rationale: str


class Condition(BaseModel):
    op: Op
    value: Any


class RelationRule(BaseModel):
    """Raw rule (never a hand label in data): evidence_type + when-condition -> per-hypothesis effect."""

    evidence_type: str
    when: Condition
    effects: Dict[str, Effect]


class TestDef(BaseModel):
    id: str
    label: str
    cost: float
    outcome_likelihoods: Dict[str, Dict[str, float]]  # hypothesis_id -> outcome_id -> P(outcome|hypothesis)
    rationale: str = ""


class ActionTemplates(BaseModel):
    work_order: str
    notification: str


class DomainPack(BaseModel):
    id: str
    name: str
    description: str = ""
    hypotheses: List[Hypothesis]
    evidence_types: List[EvidenceType]
    relation_rules: List[RelationRule] = Field(default_factory=list)
    tests: List[TestDef] = Field(default_factory=list)
    action_templates: ActionTemplates
    thresholds: Dict[str, float] = Field(default_factory=dict)

    def evidence_type(self, type_id: str) -> Optional[EvidenceType]:
        for et in self.evidence_types:
            if et.id == type_id:
                return et
        return None

    def hypothesis_ids(self) -> List[str]:
        return [h.id for h in self.hypotheses]

    def hypothesis_label(self, hypothesis_id: str) -> str:
        for h in self.hypotheses:
            if h.id == hypothesis_id:
                return h.label
        return hypothesis_id


# A feature extractor maps a pack-scenario raw reading to a list of evidence dicts.
Extractor = Callable[[Any], List[Dict[str, Any]]]


@dataclass(frozen=True)
class LoadedPack:
    pack: DomainPack
    extractors: Dict[str, Extractor] = field(default_factory=dict)
    path: Optional[Path] = None


def discover_packs(domains_dir: Path | None = None) -> List[Path]:
    """All directories under domains/ that contain a pack.json."""
    root = Path(domains_dir) if domains_dir else Path("domains")
    return sorted(p.parent for p in root.glob("*/pack.json"))


def _load_extractors(pack_dir: Path, pack_id: str) -> Dict[str, Extractor]:
    features_path = pack_dir / "features.py"
    if not features_path.exists():
        return {}
    spec = importlib.util.spec_from_file_location(f"domainpack_{pack_id}_features", features_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        return {}
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    declared = getattr(module, "EXTRACTORS", {})
    return dict(declared)


def load_pack(pack_dir: Path | str) -> LoadedPack:
    """Load and validate a DomainPack plus its optional feature extractors."""
    pack_dir = Path(pack_dir)
    manifest = pack_dir / "pack.json"
    data = json.loads(manifest.read_text(encoding="utf-8-sig"))  # utf-8-sig: tolerate BOM
    pack = DomainPack.model_validate(data)
    return LoadedPack(pack=pack, extractors=_load_extractors(pack_dir, pack.id), path=pack_dir)
