"""Trace CLI.

python cli.py --domain water_utility --scenario rainfall_reversal [--inject] [--offline]
              [--approve|--reject] [--json] [--report PATH]

--offline (or policy llm_enabled=false) runs with no API key: template hypotheses,
deterministic Challenger rules, cached/simulated weather. Online LLM calls hard-fail without
GROQ_API_KEY/GROQ_MODEL; env is validated only when an online call is actually made.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from core.actions import FileOutboxAdapter
from core.datasource import load_scenario
from core.domain import load_pack
from core.llm import make_llm_client
from core.policy import load_policy
from core.state import Status
from core.workflow import WorkflowEngine, WorkflowError


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="trace-agent", description="Trace — the investigator that tries to prove itself wrong")
    parser.add_argument("--domain", default="water_utility", help="domain pack name under domains/")
    parser.add_argument("--scenario", default="rainfall_reversal", help="scenario id under domains/<domain>/scenarios")
    parser.add_argument("--inject", action="store_true", help="inject the scenario's injected evidence (round 1)")
    parser.add_argument("--offline", action="store_true", help="force offline mode (templates + rules, no network)")
    parser.add_argument("--approve", action="store_true", help="approve the draft alert when DONE")
    parser.add_argument("--reject", action="store_true", help="reject the draft alert when DONE")
    parser.add_argument("--json", action="store_true", help="print a machine-readable summary")
    parser.add_argument("--report", default=None, help="write the outcome report to this path")
    args = parser.parse_args(argv)
    if args.approve and args.reject:
        print("--approve and --reject are mutually exclusive", file=sys.stderr)
        return 1

    policy = load_policy()
    pack_dir = Path("domains") / args.domain
    if not (pack_dir / "pack.json").exists():
        print(f"Unknown domain {args.domain!r}: {pack_dir}/pack.json not found", file=sys.stderr)
        return 1
    loaded = load_pack(pack_dir)
    offline = args.offline or not policy.llm_enabled
    engine = WorkflowEngine(
        loaded, policy, llm=make_llm_client(offline), action_adapter=FileOutboxAdapter("outbox")
    )

    try:
        scenario = load_scenario(pack_dir / "scenarios" / f"{args.scenario}.json")
        state = engine.run_scenario(scenario)
        if args.inject and scenario.injected_evidence:
            state = engine.inject_evidence(state, list(scenario.injected_evidence), note="cli --inject")
        if args.inject and state.status == Status.AWAITING_EVIDENCE and state.round < policy.max_rounds:
            state = engine.inject_evidence(state, [], note="cli round-cap filler (no new evidence)")
        if state.status == Status.DONE:
            state = engine.request_alert_draft(state)
            if args.approve:
                state = engine.approve(state, approver="cli-operator")
            elif args.reject:
                state = engine.reject(state)
    except WorkflowError as exc:
        print(f"workflow error: {exc}", file=sys.stderr)
        return 1

    snapshot = state.ranking_history[-1] if state.ranking_history else None
    summary = {
        "scenario": state.scenario_id,
        "status": state.status.value,
        "round": state.round,
        "leader": state.leader,
        "scores": snapshot.scores if snapshot else None,
        "sensitivity": state.sensitivity.model_dump() if state.sensitivity else None,
        "next_test": state.next_test.best_test if state.next_test else None,
        "challenger_findings": len(state.challenger_findings),
        "approval": state.approval.value,
        "actions": [a.action_id for a in state.actions],
        "llm": "offline templates" if offline else f"online ({getattr(engine.llm, 'model_id', 'unknown')})",
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        mode = "OFFLINE (templates + deterministic rules, no network)" if offline else "online-capable"
        print(f"Trace ({mode})")
        print(f"Scenario: {state.scenario_id} | status: {state.status.value} | round: {state.round}")
        if snapshot:
            ranked = ", ".join(f"{h}={s:.0f}" for h, s in sorted(snapshot.scores.items(), key=lambda kv: -kv[1]))
            print(f"Leader: {state.leader} | evidence scores (not probabilities): {ranked}")
            for line in snapshot.explanation[:6]:
                print(f"  {line}")
        else:
            print("No ranking emitted (INSUFFICIENT_EVIDENCE).")
        if state.sensitivity:
            print(f"Uncertainty: {state.sensitivity.label} (leader stability {state.sensitivity.leader_stability:.0%})")
        if state.next_test:
            print(f"Next test (heuristic, not exact optimisation): {state.next_test.best_test}")
        if state.alert_draft:
            print(state.alert_draft.text)
        for action in state.actions:
            print(f"Action: {action.kind} -> {action.path}")
    if args.report and state.outcome_report:
        Path(args.report).write_text(state.outcome_report, encoding="utf-8")
        print(f"Report written to {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
