# Trace — Build-day step sequence (AgentOps'26, 24 Oct 2026)

Build window 11:00–17:00; lunch ~13:30–15:00 (tentative); submission 17:00.
Work one step at a time, commit after each, STOP and wait for "go step N".
**No new architecture after 16:15.**

## Steps (each: target time — scope — done when)

- **S1 · 11:00 — Foundation and skeleton.**
  Done when: repo scaffolded (`trace-agent` package layout, `config/`, `scenarios/`, `tests/`),
  `.env` git-ignored and example provided, config schemas + empty module skeletons import,
  `pytest` runs green on a smoke test, Streamlit app boots to a placeholder.

- **S2 · 11:20 — Scenarios, ledger, Judge with source groups.**
  Done when: all 6 scenarios load and validate; ledger enforces append-only + citation validation;
  Judge computes grouped, normalised evidence scores (A/B/C tiers, strongest-per-group rule) for
  every scenario; unit tests green.

- **S2b — Sensitivity.**
  Done when: seeded 1000-run Monte Carlo returns leader-stability frequency, mean ranks,
  top-two margin, and the separable/not-separable label at a configurable cut-off; tests green.

- **S3 · 12:25 — Next-test table.**
  Done when: `config/tests.json` drives expected **entropy reduction** (primary metric) plus an
  expected **top-two-margin change** column, ranked by gain-per-cost, for every candidate; best
  test AND full table AND implication-per-outcome all derived from config; the rainfall-reversal
  scenario recommends the storm-drain or upstream sample; "heuristic, not exact optimisation"
  label present; tests green.

- **S4 — Minimal dashboard.**
  Done when: Streamlit shows scenario selector, ranked scores (labelled "evidence scores, not
  probabilities"), ledger with IDs, before/after ranking; runs fully offline.

- **S5 · 13:00 — Investigator (templates first).**
  Done when: deterministic Python anomaly detection + template hypotheses with valid citations
  work offline; LLM path validates env only when called; LLM failure falls back to templates and
  records the fallback in the ledger.

- **~13:30–15:00 · Lunch**

- **S6 · 15:00 — Challenger.**
  Done when: deterministic rules over `config/relations.json` produce contradictions + missing
  evidence from the raw ledger only; LLM findings validated (unknown citations rejected); the
  Challenger never outputs conclusions or scores; tests green.

- **S7 · 15:40 — Workflow and state machine, injection.**
  Done when: all transitions from `docs/state.md` implemented (LangGraph with a hard 10-min
  wall-clock budget and one quick retry before falling back to plain Python; README states which
  was used), round cap enforced, injection appends + re-runs + updates the snapshot diff, all
  invariants tested.

- **CUT LINE 16:15** — if the Challenger is not reliable: demo Judge re-ranking on injected
  evidence and say so plainly in the README/demo.

- **S8 — Reliability panel and dashboard finish.**
  Done when: weight table with per-tier rationale, sensitivity result, full next-test table,
  uncertainty warning, "Inject new evidence" button, Challenger findings view, and human-approval
  panel for draft alerts all live; unverified never shown as confirmed.

- **S9 — Evaluation and baselines.**
  Done when: Trace vs B2 (Investigator-only) vs B3 (simple rule) vs B1 (single-pass LLM, online
  only) on the same 6 scenarios; B1 with no key is reported as **"skipped (no key)"** in the table
  and README — never fabricated — and the model id is recorded whenever B1 runs; metrics as counts
  with misses (e.g. 5/6) — attribution, revision direction, next-test separation, next-test
  effectiveness vs random/cheapest, leader stability, 100 % citation validity; nothing invented.

- **S10 — Audit.**
  Done when: honesty statements present in README and UI; citation validity verified 100 %;
  secrets scan clean (no `.env` content anywhere); all invariant tests green.

- **S11 — README, demo script, submission.**
  Done when: README includes limitations + honesty statement; demo script walks the
  rainfall-reversal scenario end-to-end (leader change explained from real rule-derived evidence,
  illustrative 62/18/20 → 24/46/30 numbers NOT hard-coded); submission packaged by 17:00.

## Optional (only if fully on schedule)
Semi-real data (Open-Meteo with local cache vs simulated fallback; record which was used),
custom-evidence form, Ollama.

## Cut order when behind
semi-real data → custom-evidence form → extra charts → LangGraph → noisy variants → baseline B1.

## NEVER cut
source groups · sensitivity · next-test table · state-machine tests · limitations statement.
