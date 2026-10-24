"""Evaluation harness (Part 4A) — Trace vs baselines on the 6 simulated scenarios.

Variants are seeded perturbations of the same 6 cases (not independent cases). Ground truth
is read ONLY here (tests/fixtures/ground_truth.json) — agents never see it. Results are
written to docs/results.md (human) and results.json (machine-readable; read by the UI/ROI).

Baselines: Trace full; B2 Investigator-only (no Challenger, no re-assessment); B3 simple
rule (downstream breach + logged release -> factory); B1 single-pass LLM (online only —
recorded as "skipped (no key)" without a key; a number is never fabricated).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from core.actions import FileOutboxAdapter
from core.datasource import ScenarioFile, load_scenario
from core.domain import LoadedPack, load_pack
from core.evidence import EvidenceLedger
from core.llm import make_llm_client
from core.policy import load_policy
from core.scoring import _matches, assess, normalise
from core.state import Status, IncidentState
from core.workflow import WorkflowEngine

ROOT = Path(__file__).resolve().parent
SCENARIOS = ROOT / "domains" / "water_utility" / "scenarios"
GROUND_TRUTH = ROOT / "tests" / "fixtures" / "ground_truth.json"
VARIANT_SEEDS = [1, 2]  # base + 2 seeded noisy variants = 3 runs per case per config
MAX_SAMPLES = 6  # business-metric loop cap (measurements per run)


def _truth() -> Dict[str, Optional[str]]:
    return json.loads(GROUND_TRUTH.read_text(encoding="utf-8-sig"))


def _scenario_files() -> List[str]:
    return sorted(p.stem for p in SCENARIOS.glob("*.json"))


def _variant(scenario_id: str, seed: int) -> ScenarioFile:
    from domains.water_utility.features import make_noisy_variant

    raw = json.loads((SCENARIOS / f"{scenario_id}.json").read_text(encoding="utf-8-sig"))
    data = make_noisy_variant(raw, seed=seed) if seed else raw
    return ScenarioFile.model_validate(data)


def _margin(snapshot_scores: Dict[str, float]) -> float:
    ordered = sorted(snapshot_scores.values(), reverse=True)
    return ordered[0] - ordered[1]


def _rank_of(scores: Dict[str, float], hypothesis: str) -> int:
    ordered = sorted(scores, key=lambda h: (-scores[h], h))
    return ordered.index(hypothesis) + 1


def _rng(seed_text: str) -> np.random.Generator:
    return np.random.default_rng(abs(hash(seed_text)) % (2**32))


def _sample_outcome(test_def, truth: str, rng: np.random.Generator) -> str:
    outcomes = list(test_def.outcome_likelihoods[truth].items())
    values = [p for _, p in outcomes]
    values = [v / sum(values) for v in values]
    return outcomes[int(rng.choice(len(outcomes), p=values))][0]


def run_trace_full(loaded: LoadedPack, policy, scenario: ScenarioFile, tmp_outbox: Path) -> IncidentState:
    engine = WorkflowEngine(
        loaded, policy, llm=make_llm_client(offline=True), action_adapter=FileOutboxAdapter(tmp_outbox)
    )
    state = engine.run_scenario(scenario)
    injected = False
    if scenario.injected_evidence and state.round < policy.max_rounds:
        state = engine.inject_evidence(state, list(scenario.injected_evidence), note="evaluation")
        injected = True
    if injected and state.status == Status.AWAITING_EVIDENCE and state.round < policy.max_rounds:
        state = engine.inject_evidence(state, [], note="evaluation round-cap filler")
    return state


def citation_validity(state: IncidentState) -> Tuple[int, int]:
    total = invalid = 0
    for record in state.ledger.records():
        cited = record.values.get("cites", []) if isinstance(record.values, dict) else []
        if cited:
            total += len(cited)
            invalid += len(state.ledger.validate_citations(cited))
    for finding in state.challenger_findings:
        total += len(finding.cited_ids)
        invalid += len(state.ledger.validate_citations(finding.cited_ids))
    return total, invalid


# --------------------------------------------------------------------------- baselines
def b2_investigator_only(loaded: LoadedPack, policy, scenario: ScenarioFile) -> Optional[str]:
    from agents.investigator import Investigator
    from agents.judge import Judge

    llm = make_llm_client(offline=True)
    state = IncidentState(scenario_id=scenario.scenario_id)
    from core.datasource import ingest_scenario

    ingest_scenario(scenario, loaded, state.ledger)
    Investigator(loaded, llm).investigate(state)
    Judge(loaded, policy).run(state)  # single pass: no Challenger, no re-assessment
    return state.leader


def b3_simple_rule(loaded: LoadedPack, scenario: ScenarioFile) -> str:
    """Downstream breach + logged release -> factory; rainfall -> runoff; upstream -> upstream."""
    pack = loaded.pack
    ledger = EvidenceLedger()
    from core.datasource import ingest_scenario

    ingest_scenario(scenario, loaded, ledger)
    assessment = assess(ledger, pack)

    def matched(effects: Dict[str, str]) -> bool:
        for contributions in assessment.contributions.values():
            for c in contributions:
                record = ledger.get(c.record_id)
                if record and record.evidence_type and any(
                    r.evidence_type == record.evidence_type
                    and _matches(r.when, record)
                    and set(r.effects) & set(effects)
                    for r in pack.relation_rules
                ):
                    return True
        return False

    has_release = any(r.evidence_type == "discharge_log" for r in ledger.records())
    if has_release and matched({"factory_discharge"}):
        return "factory_discharge"
    if matched({"storm_runoff"}):
        return "storm_runoff"
    if matched({"upstream_source"}):
        return "upstream_source"
    return "undetermined"


def b1_single_pass_llm(loaded: LoadedPack, scenario: ScenarioFile, llm) -> Dict[str, str]:
    """Online-only baseline; with no key report 'skipped (no key)' — never fabricate."""
    if llm.offline:
        return {"status": "skipped (no key)", "model_id": "", "attribution": ""}
    from core.datasource import ingest_scenario

    ledger = EvidenceLedger()
    ingest_scenario(scenario, loaded, ledger)
    items = "\n".join(f"{r.id} [{r.evidence_type}] {r.observation}" for r in ledger.records())
    try:
        data = llm.complete_structured(
            "Attribution task. Evidence:\n" + items
            + '\nReturn JSON {"attribution": "one hypothesis id"}. Hypotheses: '
            + ", ".join(loaded.pack.hypothesis_ids())
        )
        return {"status": "ran", "model_id": llm.model_id, "attribution": str(data.get("attribution", ""))}
    except Exception as exc:
        return {"status": f"failed: {exc}", "model_id": getattr(llm, "model_id", ""), "attribution": ""}


# --------------------------------------------------------------------------- strategies
def samples_to_separable(
    loaded: LoadedPack,
    policy,
    scenario: ScenarioFile,
    truth: str,
    strategy: str,
    tmp_outbox: Path,
    seed: int,
) -> Dict[str, Any]:
    """Measurements needed until the sensitivity label is 'separable' (censored at cap)."""
    engine = WorkflowEngine(
        loaded, policy, llm=make_llm_client(offline=True), action_adapter=FileOutboxAdapter(tmp_outbox)
    )
    state = engine.run_scenario(scenario)
    if state.sensitivity is None:  # INSUFFICIENT_EVIDENCE: no ranking possible
        return {"separable": False, "samples": None, "censored": True}
    samples = 0
    rng = _rng(f"{scenario.scenario_id}|{strategy}|{seed}")
    while not state.sensitivity.separable and samples < MAX_SAMPLES:
        if state.round >= policy.max_rounds:
            break  # round cap: cannot inject further
        test_id = _pick_test(state, strategy, engine.loaded_pack.pack, rng)
        if test_id is None:
            break
        test_def = next(t for t in engine.loaded_pack.pack.tests if t.id == test_id)
        outcome = _sample_outcome(test_def, truth, rng)
        state = engine.inject_test_outcome(state, test_id, outcome)
        samples += 1
        if state.status == Status.INSUFFICIENT_EVIDENCE:
            break
    return {
        "separable": bool(state.sensitivity and state.sensitivity.separable),
        "samples": samples if state.sensitivity and state.sensitivity.separable else None,
        "censored": not (state.sensitivity and state.sensitivity.separable),
    }


def _pick_test(state: IncidentState, strategy: str, pack, rng: np.random.Generator) -> Optional[str]:
    if not pack.tests:
        return None
    if strategy == "trace":
        return state.next_test.best_test if state.next_test else None
    if strategy == "cheapest":
        return sorted(pack.tests, key=lambda t: (t.cost, t.id))[0].id
    if strategy == "random":
        return pack.tests[int(rng.integers(len(pack.tests)))].id
    raise ValueError(strategy)


# --------------------------------------------------------------------------- main
def evaluate() -> Dict[str, Any]:
    loaded = load_pack(ROOT / "domains" / "water_utility")
    policy = load_policy(ROOT / "config" / "policy.json")
    truth = _truth()
    b1_llm = make_llm_client(offline=True)  # no key in this environment
    tmp = Path(".cache") / "eval_outbox"

    cases: Dict[str, Any] = {}
    citation_total = citation_invalid = 0
    revision_cases: List[bool] = []
    separation_results: Dict[str, bool] = {}
    stability_by_case: Dict[str, List[float]] = {}
    attribution = {"trace": [], "b2": [], "b3": []}
    samples = {"trace": [], "cheapest": [], "random": []}
    margin_gain = {"trace": [], "cheapest": [], "random": []}

    for scenario_id in _scenario_files():
        expected = truth.get(scenario_id)
        case: Dict[str, Any] = {"ground_truth": expected, "runs": []}
        leaders, stabilities = [], []
        for seed in [0] + VARIANT_SEEDS:
            scenario = _variant(scenario_id, seed)
            state = run_trace_full(loaded, policy, scenario, tmp)
            total, invalid = citation_validity(state)
            citation_total += total
            citation_invalid += invalid
            run_info: Dict[str, Any] = {"seed": seed, "status": state.status.value}
            if state.status == Status.INSUFFICIENT_EVIDENCE:
                run_info["leader"] = None
                leaders.append(None)
            else:
                run_info["leader"] = state.leader
                leaders.append(state.leader)
                stabilities.append(state.sensitivity.leader_stability)
                case.setdefault("final_scores", []).append(state.ranking_history[-1].scores)

            # revision direction (only cases with injected evidence can be revised)
            if scenario.injected_evidence and len(state.ranking_history) >= 2:
                before, after = state.ranking_history[0], state.ranking_history[-1]
                if expected:
                    revision_cases.append(_rank_of(after.scores, expected) < _rank_of(before.scores, expected))
                else:
                    revision_cases.append(False)

            # next-test separation at round 0 (simulated outcome drawn from ground truth)
            if state.ranking_history and expected:
                engine = WorkflowEngine(loaded, policy, llm=make_llm_client(offline=True), action_adapter=FileOutboxAdapter(tmp))
                probe = engine.run_scenario(scenario)
                before_margin = _margin(probe.ranking_history[-1].scores)
                test_id = probe.next_test.best_test if probe.next_test else None
                if test_id:
                    test_def = next(t for t in loaded.pack.tests if t.id == test_id)
                    outcome = _sample_outcome(test_def, expected, _rng(f"{scenario_id}|sep|{seed}"))
                    probe = engine.inject_test_outcome(probe, test_id, outcome)
                    after_margin = _margin(probe.ranking_history[-1].scores) if probe.ranking_history else 0.0
                    separation_results.setdefault(scenario_id, []).append(after_margin > before_margin + 1e-9)

            attribution["trace"].append((leaders[-1] == expected) if expected else (leaders[-1] is None))
            attribution["b2"].append(b2_investigator_only(loaded, policy, scenario) == expected if expected else False)
            attribution["b3"].append(b3_simple_rule(loaded, scenario) == expected if expected else False)
            case["runs"].append(run_info)

        if stabilities:
            stability_by_case[scenario_id] = stabilities

        # business metric: measurements to separable per strategy (base + variants)
        for strategy in samples:
            per_run = [
                samples_to_separable(loaded, policy, _variant(scenario_id, seed), truth[scenario_id] or "", strategy, tmp, seed)
                for seed in [0] + VARIANT_SEEDS
            ] if truth[scenario_id] else []
            case[f"samples_to_separable_{strategy}"] = per_run
            samples[strategy].extend(per_run)

        cases[scenario_id] = case

    # next-test effectiveness: mean top-two margin gain after the recommended/cheapest/random test
    for scenario_id in _scenario_files():
        expected = truth.get(scenario_id)
        if not expected:
            continue
        for strategy in margin_gain:
            rng_seed = {"trace": 11, "cheapest": 12, "random": 13}[strategy]
            engine = WorkflowEngine(loaded, policy, llm=make_llm_client(offline=True), action_adapter=FileOutboxAdapter(tmp))
            scenario = _variant(scenario_id, rng_seed)
            probe = engine.run_scenario(scenario)
            before_margin = _margin(probe.ranking_history[-1].scores)
            test_id = _pick_test(probe, strategy, loaded.pack, _rng(f"{scenario_id}|eff|{strategy}"))
            if test_id:
                test_def = next(t for t in loaded.pack.tests if t.id == test_id)
                outcome = _sample_outcome(test_def, expected, _rng(f"{scenario_id}|eff|{strategy}"))
                probe = engine.inject_test_outcome(probe, test_id, outcome)
                after_margin = _margin(probe.ranking_history[-1].scores) if probe.ranking_history else 0.0
                margin_gain[strategy].append(round(after_margin - before_margin, 3))

    def _mean(xs: List[float]) -> Optional[float]:
        return round(sum(xs) / len(xs), 4) if xs else None

    def _count(xs: List[bool]) -> str:
        return f"{sum(1 for x in xs if x)}/{len(xs)}"

    def _samples_stats(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
        measured = [r["samples"] for r in runs if r["separable"] and r["samples"] is not None]
        censored = sum(1 for r in runs if not r["separable"])
        return {
            "runs": len(runs),
            "reached_separable": f"{len(measured)}/{len(runs)}",
            "mean_samples_when_separable": _mean([float(m) for m in measured]),
            "censored_runs": censored,
        }

    b1_results = {
        scenario_id: b1_single_pass_llm(loaded, _variant(scenario_id, 0), b1_llm)
        for scenario_id in _scenario_files()
    }

    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {
            "variant_seeds": VARIANT_SEEDS,
            "runs_per_case": 1 + len(VARIANT_SEEDS),
            "max_rounds": policy.max_rounds,
            "separability_cutoff": policy.separability_cutoff,
            "max_samples": MAX_SAMPLES,
            "note": "variants are perturbations of the same 6 cases, not independent cases",
        },
        "per_case": cases,
        "metrics": {
            "attribution_after_all_evidence": {
                "trace": _count(attribution["trace"]),
                "b2_investigator_only": _count(attribution["b2"]),
                "b3_simple_rule": _count(attribution["b3"]),
                "b1_single_pass_llm": "skipped (no key)" if b1_llm.offline else "ran (see per_case)",
                "misses": [
                    {"scenario": sid, "expected": truth.get(sid)}
                    for sid in _scenario_files()
                    if truth.get(sid) and not all(
                        (cases[sid]["runs"][i]["leader"] == truth.get(sid))
                        for i in range(len(cases[sid]["runs"]))
                    )
                ],
            },
            "ranking_revised_right_direction": {
                "cases_with_injected_evidence": len({sid for sid in _scenario_files() if _variant(sid, 0).injected_evidence}),
                "revised_correctly": _count(revision_cases) if revision_cases else "n/a (only rainfall_reversal ships injected evidence)",
            },
            "next_test_separates_top_two": {
                "count": _count([x for xs in separation_results.values() for x in xs]),
                "per_case": {k: _count(v) for k, v in separation_results.items()},
            },
            "next_test_effectiveness_mean_margin_gain": {k: _mean(v) for k, v in margin_gain.items()},
            "business_metric_measurements_to_separable": {k: _samples_stats(v) for k, v in samples.items()},
            "leader_stability_mean": _mean([s for xs in stability_by_case.values() for s in xs]),
            "citation_validity": {
                "total_citations": citation_total,
                "invalid": citation_invalid,
                "rate": "100%" if citation_invalid == 0 else f"{100 * (1 - citation_invalid / max(citation_total, 1)):.1f}%",
            },
        },
        "b1_per_scenario": b1_results,
    }
    return results


def main() -> int:
    results = evaluate()
    Path("results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    write_results_md(results)
    print("evaluation written to results.json and docs/results.md")
    return 0


def write_results_md(results: Dict[str, Any]) -> None:
    m = results["metrics"]
    lines = [
        "# Evaluation results (simulated scenarios only)",
        "",
        f"Generated: {results['generated_at']}. Variants are seeded perturbations of the same 6 cases "
        f"(seeds {results['config']['variant_seeds']}); they are NOT independent cases. "
        "All numbers below are measured on simulated data and give no real-world validation.",
        "",
        "| Metric | Result |",
        "|---|---|",
        f"| Correct attribution after all evidence - Trace | {m['attribution_after_all_evidence']['trace']} |",
        f"- B2 Investigator-only | {m['attribution_after_all_evidence']['b2_investigator_only']} |" if False else f"| Correct attribution - B2 (Investigator-only) | {m['attribution_after_all_evidence']['b2_investigator_only']} |",
        f"| Correct attribution - B3 (simple rule) | {m['attribution_after_all_evidence']['b3_simple_rule']} |",
        f"| Correct attribution - B1 (single-pass LLM) | {m['attribution_after_all_evidence']['b1_single_pass_llm']} |",
        f"| Ranking revised in the right direction | {m['ranking_revised_right_direction']['revised_correctly']} |",
        f"| Next test separates the top two | {m['next_test_separates_top_two']['count']} |",
        f"| Next-test mean margin gain (Trace vs cheapest vs random) | {m['next_test_effectiveness_mean_margin_gain']} |",
        f"| Measurements to 'separable' - Trace | {m['business_metric_measurements_to_separable']['trace']} |",
        f"| Measurements to 'separable' - cheapest-first | {m['business_metric_measurements_to_separable']['cheapest']} |",
        f"| Measurements to 'separable' - random | {m['business_metric_measurements_to_separable']['random']} |",
        f"| Mean leader stability | {m['leader_stability_mean']} |",
        f"| Citation validity | {m['citation_validity']['rate']} ({m['citation_validity']['invalid']} invalid of {m['citation_validity']['total_citations']}) |",
        "",
        "## Misses",
        "",
    ]
    for miss in m["attribution_after_all_evidence"]["misses"]:
        lines.append(f"- {miss['scenario']}: expected {miss['expected']}")
    if not m["attribution_after_all_evidence"]["misses"]:
        lines.append("- None recorded (but B1 was skipped without a key, so it has no result).")
    lines += ["", "Business-value metrics are measured only in simulation - never claim real savings.",
              "", "## Per-case detail", ""]
    for sid, case in results["per_case"].items():
        lines.append(f"### {sid} (ground truth: {case['ground_truth']})")
        for run in case["runs"]:
            lines.append(f"- seed {run['seed']}: status {run['status']}, leader {run['leader']}")
        lines.append("")
    (ROOT / "docs" / "results.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
