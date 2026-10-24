# Trace — build progress

Updated after every part so work can resume after a context loss. Working dir:
`C:\Users\Ananya\OneDrive\Desktop\trace` (venv: `.venv`, Python 3.12.3).

| Part | Scope | Status | Tests |
|---|---|---|---|
| S0 | Docs and rules (AGENTS, brief, state, scoring, steps, decisions) | done | n/a |
| S1 | Skeleton: pack loader, policy, LLM clients, UI/CLI smoke | done | 8 passed |
| S2A | Pack + scenarios + extractors + noisy variants | done | 8 passed |
| S2B | Ledger extensions, policy, DataSource | done | 8 passed |
| S2C | Judge + scoring (groups, normalisation, diff) | done | 8 passed |
| S2D | Sensitivity (seeded MC) | done | 8 passed |
| S2E | Next-test (entropy reduction + margin column) | done | 8 passed |
| S2F | Step-2 test suite | done | 21 passed |
| 3A | LLM layer + Open-Meteo rainfall tool | done | 27 passed |
| 3B | Investigator | done | 31 passed |
| 3C | Challenger | done | 35 passed |
| 3D | Workflow / state machine (LangGraph driver verified) | done | 46 passed |
| 3E | Actions + outcome report | done | 46 passed |
| 3F | CLI + workflow tests | done | 47 passed |
| 4A | Evaluation + baselines (results.md/results.json) | in progress | — |
| 4B | docs/governance.md | pending | — |
| 4C | core/roi.py | pending | — |
| 4D | Deploy prep + healthcheck | pending | — |
