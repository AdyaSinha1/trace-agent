"""DataSource: JSON/CSV loaders with schema validation and clear errors.

Upload format (used later by the UI custom-evidence form):
- Scenario JSON: {"scenario_id", "simulated", "pack", "incident_time", "raw" {...},
  "initial_evidence": [<EvidenceRecord>...], "injected_evidence": [<EvidenceRecord>...]}
- Evidence CSV: header row with columns id, source, source_group, timestamp, location,
  observation, kind, reliability, [evidence_type], [values (JSON object string)].

All loaders raise DataSourceError with the path and the reason; they never crash the app.
ingest_scenario() is domain-agnostic: it appends scenario evidence and runs every registered
pack feature extractor over the raw readings.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel, Field, ValidationError

from core.domain import LoadedPack
from core.evidence import EvidenceKind, EvidenceLedger, EvidenceRecord


class DataSourceError(Exception):
    """Raised for any unreadable/invalid data source; message is user-facing."""


class ScenarioFile(BaseModel):
    scenario_id: str
    simulated: bool = True
    pack: str = ""
    incident_time: str = ""
    raw: Dict[str, Any] = Field(default_factory=dict)
    initial_evidence: List[EvidenceRecord] = Field(default_factory=list)
    injected_evidence: List[EvidenceRecord] = Field(default_factory=list)


def load_scenario(path: Path | str) -> ScenarioFile:
    """Load and validate a scenario JSON file."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise DataSourceError(f"cannot read scenario {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise DataSourceError(f"scenario {path} is not valid JSON: {exc}") from exc
    try:
        return ScenarioFile.model_validate(data)
    except ValidationError as exc:
        required = "scenario_id, raw{sensor_readings, discharge_log, rainfall}, initial/injected_evidence"
        raise DataSourceError(f"scenario {path} failed validation ({required}): {exc.error_count()} error(s); first: {exc.errors()[0]['msg']}") from exc


def load_evidence_csv(path: Path | str) -> List[EvidenceRecord]:
    """Load evidence rows from CSV (columns documented in the module docstring)."""
    path = Path(path)
    required = {"id", "source", "source_group", "timestamp", "location", "observation", "kind", "reliability"}
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            headers = set(reader.fieldnames or [])
            missing = required - headers
            if missing:
                raise DataSourceError(f"CSV {path} missing required columns: {sorted(missing)}")
            records: List[EvidenceRecord] = []
            for row_no, row in enumerate(reader, start=2):
                try:
                    values = json.loads(row.get("values") or "{}")
                    if not isinstance(values, dict):
                        raise ValueError("values must be a JSON object")
                    records.append(
                        EvidenceRecord(
                            id=row["id"].strip(),
                            source=row["source"],
                            source_group=row["source_group"],
                            timestamp=row["timestamp"],
                            location=row["location"],
                            observation=row["observation"],
                            kind=EvidenceKind(row["kind"].strip()),
                            reliability=float(row["reliability"]),
                            evidence_type=(row.get("evidence_type") or "").strip() or None,
                            values=values,
                        )
                    )
                except (ValueError, KeyError, ValidationError) as exc:
                    raise DataSourceError(f"CSV {path} row {row_no}: invalid evidence row ({exc})") from exc
            return records
    except OSError as exc:
        raise DataSourceError(f"cannot read CSV {path}: {exc}") from exc


def ingest_scenario(
    scenario: ScenarioFile, loaded_pack: LoadedPack, ledger: EvidenceLedger
) -> List[EvidenceRecord]:
    """Append scenario evidence (initial only; injected on request by the caller) and run
    every registered pack feature extractor over the raw readings. Returns what was appended."""
    appended: List[EvidenceRecord] = []
    for record in scenario.initial_evidence:
        try:
            appended.append(ledger.append(record))
        except ValueError as exc:
            raise DataSourceError(f"scenario {scenario.scenario_id}: {exc}") from exc

    context = {
        "raw": scenario.raw,
        "incident_time": scenario.incident_time,
        "thresholds": loaded_pack.pack.thresholds,
        "scenario_id": scenario.scenario_id,
    }
    for name in sorted(loaded_pack.extractors):
        for i, item in enumerate(loaded_pack.extractors[name](context)):
            payload = dict(item)
            payload.setdefault("kind", EvidenceKind.TOOL_OUTPUT)
            payload.setdefault("id", f"{scenario.scenario_id}:{name}:{i}")
            try:
                appended.append(ledger.append(EvidenceRecord.model_validate(payload)))
            except ValidationError as exc:
                raise DataSourceError(
                    f"extractor {name!r} produced an invalid evidence item: {exc.errors()[0]['msg']}"
                ) from exc
            except ValueError as exc:
                raise DataSourceError(f"extractor {name!r}: {exc}") from exc
    return appended
