# Trace (`trace-agent`)

An investigator that tries to prove itself wrong. For a simulated water-pollution incident it
ranks three competing explanations (factory discharge, storm runoff, upstream source), challenges
its own leading hypothesis against raw evidence, re-ranks when new evidence arrives and explains
why, and recommends the next measurement that best separates the remaining explanations.

**Process:** data ingestion -> intelligent decision-making -> action execution -> outcome reporting.
**Architecture:** three agents sharing one append-only evidence ledger — Investigator (LLM +
deterministic tools), Challenger (rules first, LLM only if enabled; sees only the leader + raw
ledger), Judge (pure Python; the only component that scores). The LLM never sets or edits a score.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## One-command offline demo (no API key)

```powershell
.venv\Scripts\python cli.py --domain water_utility --scenario rainfall_reversal --inject --approve --offline --report demo_report.md
```

Or the UI: `.venv\Scripts\streamlit run app.py` -> pick the rainfall scenario -> Open investigation
-> Board (inject) -> Challenge/Next test -> Approval. Tests: `.venv\Scripts\python -m pytest`.

## Limitations (honest)

- **All data and all actions are simulated.** Work orders are JSON files marked "simulated";
  notifications are drafts marked "DRAFT, NOT SENT"; nothing is ever sent.
- Weights are **expert-assigned priors** (structured-analysis/ACH practice), **not fitted** to data.
- Scores are **evidence scores, not probabilities**; a narrow margin is labelled not separable.
- **Evaluation against baselines is NOT completed** — `evaluate.py` was written but has not been
  run/verified; no baseline numbers are claimed anywhere.
- **No real-world validation.** Six hand-built scenarios plus seeded noisy variants only.

## Adding a domain pack (6 lines)

1. Create `domains/<your_domain>/pack.json` with hypotheses, evidence types (tier, weight,
   rationale), relation rules, tests, action templates, thresholds.
2. Optionally add `features.py` with pure-Python extractors (raw readings -> evidence items)
   registered in `EXTRACTORS`.
3. Add scenarios as JSON under `domains/<your_domain>/scenarios/` (format documented in
   `core/datasource.py`).
4. Nothing else: the engine, agents, Judge, state machine and UI read everything from the pack.
5. See `domains/water_utility/` as the reference and `tests/fixtures/fake_pack.json` for a
   minimal example that runs Judge, sensitivity and next-test with zero code changes.
6. Run `pytest` — the fake-pack engine test proves nothing is hard-coded to water.

## Deploy (Streamlit Community Cloud)

- Main file: `app.py`. Python 3.12. `requirements.txt` pinned.
- No secrets needed: offline mode is the default (`llm_enabled=false` in `config/policy.json`);
  the app runs with no API key. Optional online LLM: set `GROQ_API_KEY` and `GROQ_MODEL` as
  Streamlit secrets or env vars — a missing `GROQ_MODEL` hard-fails online calls (no guessed
  default). Read-only filesystems fall back to a temp directory for `outbox/` and `.cache/`.
