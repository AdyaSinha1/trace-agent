"""Step 2 tests: scoring, sensitivity, next-test, ledger discipline, domain-agnosticism.

No LLM anywhere. Ground truth lives only in tests/fixtures and is read by tests only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.datasource import ingest_scenario, load_scenario
from core.domain import load_pack
from core.evidence import EvidenceKind, EvidenceLedger, EvidenceRecord
from core.policy import Policy, load_policy
from core.sampling import recommend_next_test
from core.scoring import InsufficientEvidenceError, LABEL, rank
from core.sensitivity import sensitivity
from core.state import IncidentState, Status

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "domains" / "water_utility" / "scenarios"


def build_ledger(scenario_name: str, include_injected: bool = False) -> tuple[EvidenceLedger, object]:
    loaded = load_pack(ROOT / "domains" / "water_utility")
    scenario = load_scenario(SCENARIOS / f"{scenario_name}.json")
    ledger = EvidenceLedger()
    ingest_scenario(scenario, loaded, ledger)
    if include_injected:
        for record in scenario.injected_evidence:
            ledger.append(record)
    return ledger, loaded


def make_state(ledger: EvidenceLedger, scenario_id: str) -> IncidentState:
    return IncidentState(scenario_id=scenario_id, ledger=ledger)


def test_ranking_is_reproducible() -> None:
    ledger, loaded = build_ledger("clear_factory")
    policy = load_policy(ROOT / "config" / "policy.json")
    first = rank(ledger, loaded.pack, policy)
    second = rank(ledger, loaded.pack, policy)
    assert first.snapshot.scores == second.snapshot.scores
    assert first.snapshot.leader == second.snapshot.leader
    assert "evidence scores, not probabilities" in " ".join(first.snapshot.explanation)


def test_sensitivity_is_seeded_and_reproducible() -> None:
    ledger, loaded = build_ledger("clear_factory")
    policy = load_policy(ROOT / "config" / "policy.json")
    first = sensitivity(ledger, loaded.pack, cutoff=policy.separability_cutoff, seed=7)
    second = sensitivity(ledger, loaded.pack, cutoff=policy.separability_cutoff, seed=7)
    assert first.leader_stability == second.leader_stability
    assert first.mean_rank == second.mean_rank
    other = sensitivity(ledger, loaded.pack, cutoff=policy.separability_cutoff, seed=8)
    assert other.runs == 1000  # default run count


def test_missing_data_gives_insufficient_evidence() -> None:
    from agents.judge import Judge

    ledger, loaded = build_ledger("missing_data")
    policy = load_policy(ROOT / "config" / "policy.json")
    with pytest.raises(InsufficientEvidenceError):
        rank(ledger, loaded.pack, policy)
    state = Judge(loaded, policy).run(make_state(ledger, "missing_data"))
    assert state.status == Status.INSUFFICIENT_EVIDENCE
    assert state.ranking_history == []  # no ranking emitted
    assert state.leader is None  # scores only from the Judge — and none were produced


def test_contradictory_evidence_drops_the_leader() -> None:
    ledger, loaded = build_ledger("clear_factory")
    policy = load_policy(ROOT / "config" / "policy.json")
    before = rank(ledger, loaded.pack, policy).snapshot
    assert before.leader == "factory_discharge"
    ledger.append(
        EvidenceRecord(
            id="cf-lab-clears",
            source="accredited_lab",
            source_group="lab_sample",
            timestamp="2026-06-10T16:00:00",
            location="downstream",
            observation="downstream sample: no industrial signature",
            kind=EvidenceKind.OBSERVATION,
            reliability=1.0,
            evidence_type="lab_sample",
            values={"value": "no_industrial_signature"},
        )
    )
    after = rank(ledger, loaded.pack, policy).snapshot
    assert after.scores["factory_discharge"] < before.scores["factory_discharge"]
    assert after.leader != "factory_discharge"


def test_citation_validation() -> None:
    ledger, _ = build_ledger("clear_factory")
    assert ledger.citations_valid(["cf-rep1"])
    assert not ledger.citations_valid(["cf-rep1", "nope"])
    assert ledger.validate_citations(["nope", "cf-rep1", "nah"]) == ["nope", "nah"]


def test_correlated_readings_are_not_double_counted() -> None:
    loaded = load_pack(ROOT / "domains" / "water_utility")
    policy = Policy(min_total_weight=1.0)  # isolate the effect from the threshold

    def record(rid: str) -> EvidenceRecord:
        return EvidenceRecord(
            id=rid,
            source="sensor:downstream",
            source_group="downstream:ph:post_incident",
            timestamp="2026-06-10T15:00:00",
            location="downstream",
            observation="pH 6.0",
            kind=EvidenceKind.OBSERVATION,
            reliability=0.5,
            evidence_type="sensor_ph",
            values={"value": 6.0},
        )

    one = EvidenceLedger()
    one.append(record("s1"))
    two = EvidenceLedger()
    two.append(record("s1"))
    two.append(record("s2"))  # same source_group: correlated
    raw_one = rank(one, loaded.pack, policy).raw_scores["factory_discharge"]
    raw_two = rank(two, loaded.pack, policy).raw_scores["factory_discharge"]
    assert raw_one == raw_two  # strongest-per-group: the second reading adds nothing


def test_unknown_evidence_type_gets_weight_zero_and_is_flagged() -> None:
    ledger, loaded = build_ledger("clear_factory")
    policy = load_policy(ROOT / "config" / "policy.json")
    before = rank(ledger, loaded.pack, policy)
    ledger.append(
        EvidenceRecord(
            id="cf-weird",
            source="phone_call",
            source_group="hearsay",
            timestamp="2026-06-10T16:30:00",
            location="river",
            observation="someone said the water looked strange",
            kind=EvidenceKind.INJECTED,
            reliability=0.5,
            evidence_type="mystery_type",
        )
    )
    after = rank(ledger, loaded.pack, policy)
    assert after.snapshot.scores == before.snapshot.scores  # weight 0: no effect
    assert "mystery_type" in after.assessment.unknown_types  # flagged
    assert not any(c.record_id == "cf-weird" for cs in after.assessment.contributions.values() for c in cs)


def test_rainfall_reversal_drops_factory_rank() -> None:
    from agents.judge import Judge

    loaded = load_pack(ROOT / "domains" / "water_utility")
    policy = load_policy(ROOT / "config" / "policy.json")
    scenario = load_scenario(SCENARIOS / "rainfall_reversal.json")
    state = make_state(EvidenceLedger(), "rainfall_reversal")
    ingest_scenario(scenario, loaded, state.ledger)
    judge = Judge(loaded, policy)
    judge.run(state)
    assert state.ranking_history[0].leader == "factory_discharge"
    assert state.ranking_history[0].scores["factory_discharge"] > 50.0

    for record in scenario.injected_evidence:
        state.ledger.append(record)
    judge.run(state)
    before, after = state.ranking_history[0], state.ranking_history[-1]
    assert after.scores["factory_discharge"] < before.scores["factory_discharge"]

    def position(snapshot, hypothesis_id: str) -> int:
        ordered = sorted(snapshot.scores, key=lambda h: (-snapshot.scores[h], h))
        return ordered.index(hypothesis_id) + 1

    assert position(before, "factory_discharge") == 1
    assert position(after, "factory_discharge") == 3  # rank dropped after real rule-derived evidence
    # "why the leader changed": the snapshot diff explains which groups moved and by how much
    assert any("rainfall_gauge" in line or "upstream_chain" in line for line in after.explanation)


def test_clear_scenarios_separable_and_ambiguous_not() -> None:
    policy = load_policy(ROOT / "config" / "policy.json")
    for name, expected in [
        ("clear_factory", "separable"),
        ("clear_runoff", "separable"),
        ("ambiguous_mixed", "not separable"),
        ("ambiguous_upstream", "not separable"),
    ]:
        ledger, loaded = build_ledger(name)
        result = sensitivity(ledger, loaded.pack, cutoff=policy.separability_cutoff)
        assert result.label == expected, f"{name}: {result.label} (stability={result.leader_stability})"


def test_next_test_for_rainfall_reversal_is_storm_drain_or_upstream_sample() -> None:
    from agents.judge import Judge

    loaded = load_pack(ROOT / "domains" / "water_utility")
    policy = load_policy(ROOT / "config" / "policy.json")
    scenario = load_scenario(SCENARIOS / "rainfall_reversal.json")
    state = make_state(EvidenceLedger(), "rainfall_reversal")
    ingest_scenario(scenario, loaded, state.ledger)
    for record in scenario.injected_evidence:
        state.ledger.append(record)
    judge = Judge(loaded, policy)
    judge.run(state)
    judge.choose_next_test(state)
    assert state.next_test is not None
    assert state.next_test.best_test in {"sample_storm_drain", "sample_upstream_outlet"}
    assert "heuristic" in state.next_test.rationale.lower()
    assert len(state.next_test.table) == 6
    best_row = next(r for r in state.next_test.table if r["test_id"] == state.next_test.best_test)
    assert best_row["implications"]  # what each possible result would imply, from config


def test_engine_is_domain_agnostic_with_fake_pack() -> None:
    """A tiny non-water pack must drive Judge + sensitivity + next test with zero code changes."""
    from agents.judge import Judge

    pack_path = ROOT / "tests" / "fixtures" / "fake_pack.json"
    assert "water" not in json.loads(pack_path.read_text(encoding="utf-8-sig"))["id"]
    loaded = load_pack(pack_path.parent) if (pack_path.parent / "pack.json").exists() else None
    assert loaded is None  # fixtures dir is not a pack dir; build LoadedPack directly
    from core.domain import DomainPack, LoadedPack

    pack = DomainPack.model_validate(json.loads(pack_path.read_text(encoding="utf-8-sig")))
    loaded = LoadedPack(pack=pack, extractors={})
    policy = load_policy(ROOT / "config" / "policy.json")

    def record(rid: str, etype: str, value, group: str, reliability: float) -> EvidenceRecord:
        return EvidenceRecord(
            id=rid,
            source="test",
            source_group=group,
            timestamp="2026-01-01T00:00:00",
            location="loc",
            observation=f"{etype}={value}",
            kind=EvidenceKind.OBSERVATION,
            reliability=reliability,
            evidence_type=etype,
            values={"value": value},
        )

    ledger = EvidenceLedger()
    ledger.append(record("t1", "direct_record", True, "log", 1.0))  # alpha +3
    ledger.append(record("t2", "reading", 12.0, "station", 0.5))  # beta +1, alpha -1
    ledger.append(record("t3", "model", "yes", "model", 0.5))  # gamma +1

    state = make_state(ledger, "fake_incident")
    judge = Judge(loaded, policy)
    judge.run(state)
    assert state.leader == "alpha"
    assert len(state.ranking_history) == 1

    judge.assess_uncertainty(state, runs=100, seed=3)
    assert state.sensitivity is not None
    assert state.sensitivity.label in {"separable", "not separable"}

    judge.choose_next_test(state)
    assert state.next_test.best_test == "probe"
    assert len(state.next_test.table) == 1


def test_noisy_variant_is_seeded_and_changes_readings() -> None:
    from domains.water_utility.features import make_noisy_variant

    scenario = json.loads((SCENARIOS / "clear_factory.json").read_text(encoding="utf-8-sig"))
    variant_a = make_noisy_variant(scenario, seed=42)
    variant_b = make_noisy_variant(scenario, seed=42)
    assert variant_a == variant_b  # deterministic
    original_ph = scenario["raw"]["sensor_readings"][0]["value"]
    assert variant_a["raw"]["sensor_readings"] != scenario["raw"]["sensor_readings"]
    assert scenario["raw"]["sensor_readings"][0]["value"] == original_ph  # original untouched


def test_ledger_json_export_roundtrip() -> None:
    ledger, _ = build_ledger("clear_factory")
    restored = EvidenceLedger.from_records(json.loads(ledger.to_json()))
    assert len(restored) == len(ledger)
    assert {r.id for r in restored.records()} == {r.id for r in ledger.records()}
