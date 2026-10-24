"""Trace CLI. `python cli.py --offline` runs with no API key (offline mode).

Online LLM calls hard-fail without GROQ_API_KEY/GROQ_MODEL; env is validated only when an
online call is actually made.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from core.domain import discover_packs, load_pack
from core.policy import load_policy


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="trace-agent", description="Trace — incident investigator")
    parser.add_argument("--offline", action="store_true", help="run with no API key: templates + rules only")
    parser.add_argument("--pack", default=None, help="domain pack name under domains/ (default: first found)")
    args = parser.parse_args(argv)

    policy = load_policy()
    packs = discover_packs()
    if not packs:
        print("No domain packs found under domains/.")
        return 1
    pack_dir = next((p for p in packs if p.name == args.pack), packs[0])
    if args.pack and pack_dir.name != args.pack:
        print(f"Unknown pack {args.pack!r}. Available: {', '.join(p.name for p in packs)}")
        return 1

    loaded = load_pack(pack_dir)
    pack = loaded.pack
    mode = "OFFLINE (templates + deterministic rules, no network)" if args.offline else "online-capable"

    print(f"Trace ({mode})")
    print(f"Pack: {pack.id} — {pack.name}")
    if pack.description:
        print(f"  {pack.description}")
    print(f"Policy: max_rounds={policy.max_rounds} min_total_weight={policy.min_total_weight} "
          f"separability_cutoff={policy.separability_cutoff} llm_enabled={policy.llm_enabled}")
    print("Hypotheses:")
    for h in pack.hypotheses:
        print(f"  - {h.id}: {h.label}")
    print("Evidence types (expert priors, not fitted):")
    for et in pack.evidence_types:
        print(f"  - {et.id} [{et.tier}] weight={et.weight} — {et.rationale}")
    print(f"Relation rules: {len(pack.relation_rules)} | Tests: {len(pack.tests)} | "
          f"Feature extractors: {len(loaded.extractors)}")
    print("Scores will be evidence scores, not probabilities. All data simulated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
