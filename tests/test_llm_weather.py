"""Tests for the LLM layer and the water rainfall tool (no network in tests)."""

from __future__ import annotations

import pytest

from core.llm import GroqLLMClient, TemplateLLMClient, make_llm_client


def test_offline_is_the_default_client() -> None:
    client = make_llm_client(offline=True)
    assert client.offline is True
    assert client.model_id == "offline-templates"
    assert isinstance(client.complete("hello"), str)
    assert client.complete_structured("hello") == {}


def test_groq_hard_fails_without_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_MODEL"):
        GroqLLMClient().model_id  # no guessed default


def test_groq_hard_fails_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    client = GroqLLMClient()
    monkeypatch.setenv("GROQ_MODEL", "test-model")
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        client.complete("hello")


def test_structured_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.llm import _parse_json

    assert _parse_json('noise {"a": 1} trailing') == {"a": 1}
    with pytest.raises(ValueError):
        _parse_json("no json here")


def test_rainfall_tool_simulated_fallback_offline(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from domains.water_utility.weather import open_meteo_rainfall, rainfall_to_evidence

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr("requests.get", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    data = open_meteo_rainfall(12.9, 77.6, "2026-06-14", "2026-06-15", cache_dir=tmp_path)
    assert data["source"] == "simulated"
    again = open_meteo_rainfall(12.9, 77.6, "2026-06-14", "2026-06-15", cache_dir=tmp_path)
    assert again["total_mm"] == data["total_mm"]  # deterministic
    evidence = rainfall_to_evidence(data, "2026-06-15T15:00:00")
    assert evidence["evidence_type"] == "rainfall_inference"
    assert "source: simulated" in evidence["observation"]


def test_rainfall_tool_caches_network_response(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from domains.water_utility.weather import open_meteo_rainfall

    calls = {"n": 0}

    class FakeResp:
        def raise_for_status(self): ...

        def json(self):
            return {"daily": {"time": ["2026-06-14", "2026-06-15"], "rain_sum": [20.0, 8.0]}}

    def fake_get(*a, **k):
        calls["n"] += 1
        return FakeResp()

    monkeypatch.setattr("requests.get", fake_get)
    first = open_meteo_rainfall(1.0, 2.0, "2026-06-14", "2026-06-15", cache_dir=tmp_path)
    assert first["source"] == "open_meteo" and first["total_mm"] == 28.0
    second = open_meteo_rainfall(1.0, 2.0, "2026-06-14", "2026-06-15", cache_dir=tmp_path)
    assert second["source"] == "cache" and second["total_mm"] == 28.0
    assert calls["n"] == 1
