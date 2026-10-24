"""Step 1 smoke tests: imports, config loading, ledger rules, LLM env contract, CLI offline."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

CORE_MODULES = [
    "core.domain",
    "core.evidence",
    "core.scoring",
    "core.sensitivity",
    "core.sampling",
    "core.workflow",
    "core.state",
    "core.actions",
    "core.report",
    "core.policy",
    "core.llm",
    "core.roi",
    "agents.investigator",
    "agents.challenger",
    "agents.judge",
]


def test_modules_import() -> None:
    for name in CORE_MODULES:
        assert importlib.import_module(name) is not None, name


def test_load_policy() -> None:
    from core.policy import Policy, load_policy

    policy = load_policy(ROOT / "config" / "policy.json")
    assert policy.approval_required_for_actions is True
    assert policy.max_rounds == 2
    assert policy.separability_cutoff == 0.7
    assert policy.external_notifications is False
    assert Policy().max_rounds == 2  # safe defaults without a file


def test_load_water_pack() -> None:
    from core.domain import load_pack

    loaded = load_pack(ROOT / "domains" / "water_utility")
    pack = loaded.pack
    assert len(pack.hypotheses) == 3
    assert [h.id for h in pack.hypotheses] == [
        "factory_discharge",
        "storm_runoff",
        "upstream_source",
    ]
    weights = {et.id: (et.tier, et.weight) for et in pack.evidence_types}
    assert weights["discharge_log"] == ("A", 3.0)
    assert weights["sensor_ph"] == ("B", 2.0)
    assert weights["rainfall_inference"] == ("C", 1.0)
    assert pack.relation_rules and pack.tests and pack.action_templates.work_order
    assert len(loaded.extractors) >= 5  # water pack registers pure-Python feature extractors


def test_ledger_append_only_and_citations() -> None:
    from core.evidence import EvidenceKind, EvidenceLedger, EvidenceRecord

    def record(rid: str) -> EvidenceRecord:
        return EvidenceRecord(
            id=rid,
            source="sensor",
            source_group="downstream_probe",
            timestamp="2026-10-24T09:00:00",
            location="outfall",
            observation="pH 6.1",
            kind=EvidenceKind.OBSERVATION,
        )

    ledger = EvidenceLedger()
    ledger.append(record("ev1"))
    with pytest.raises(ValueError):
        ledger.append(record("ev1"))  # append-only: duplicate ids rejected
    assert ledger.citations_valid(["ev1"])
    assert not ledger.citations_valid(["ev1", "missing"])  # unknown ids rejected
    assert len(ledger.records()) == 1


def test_template_llm_offline() -> None:
    from core.llm import TemplateLLMClient

    client = TemplateLLMClient()
    assert client.offline is True
    assert isinstance(client.complete("Propose hypotheses."), str)


def test_groq_client_hard_fails_without_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.llm import GroqLLMClient

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_MODEL"):
        GroqLLMClient().complete("hello")  # no default is guessed


def test_groq_client_hard_fails_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.llm import GroqLLMClient

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        GroqLLMClient().complete("hello")


def test_cli_offline_runs() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "cli.py"), "--offline"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OFFLINE" in result.stdout
    assert "factory_discharge" in result.stdout
