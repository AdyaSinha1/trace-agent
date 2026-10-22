# AGENTS.md — Trace (project name `trace-agent`)

Working rules for any coding agent or human in this repo. Full brief: `docs/brief.md`.
Discipline: small steps, commit after each step, then STOP until the human says "go step N".

## What this is
"Trace" — an investigator that tries to prove itself wrong. For a simulated water-pollution
incident it ranks three competing explanations (factory_discharge, storm_runoff, upstream_source),
challenges its own leading explanation using raw evidence, re-ranks when new evidence arrives and
explains why, and recommends the next measurement that best separates the remaining explanations.
Track: Agents for Sustainable Development (SDG 6). Selection condition from the evaluator:
scientifically defensible attribution + measurable improvement over baselines. Build for that.

## Architecture (fixed; ask the human before any change)
- Three agents sharing one append-only evidence ledger. There is NO fourth agent.
  1. Investigator (LLM + Python tools): reads records, detects anomalies with deterministic
     Python, proposes the three hypotheses with supporting evidence IDs.
  2. Challenger (deterministic rules first, then LLM): receives ONLY the leading hypothesis and
     the raw ledger evidence, never the Investigator's reasoning. Returns contradictions and
     missing evidence. It never states a conclusion and never touches scores.
  3. Judge (pure Python, NO LLM): applies weights, re-ranks, explains what changed, estimates
     uncertainty, and chooses the next test.
- The LLM (Groq, Llama, model id from env GROQ_MODEL) never sets or edits a score.

## Evidence ledger
- Append-only. Fields: id, source, source_group, timestamp, location, observation,
  kind (observation | tool_output | agent_claim | injected),
  reliability (verified = 1.0 | unverified = 0.5).
- Every claim by any agent must cite existing ledger IDs; reject output citing unknown IDs.
- Data stores RAW observations only. Supports/contradicts relations come from rules in
  config/relations.json, never hand labels in the data. Ground truth lives only in
  tests/fixtures; agents never read it.

## Scoring (details: docs/scoring.md)
- raw_h = max(0.1, 1.0 + sum(signed_weight x reliability)) over independent evidence groups;
  normalise to 100. Scores are evidence scores, NOT probabilities — label them so everywhere.
- Weight tiers (expert-assigned priors from structured-analysis/ACH practice, NOT fitted):
  A = verified direct record (discharge log, lab sample) = 3; B = in-situ sensor reading = 2;
  C = indirect or modelled (e.g. rainfall inference) = 1. Each tier has a one-line written rationale.
- Correlated observations: each item carries source_group; within a group only the strongest
  signed weight per hypothesis counts.
- Unknown evidence type = weight 0, flagged (judge/user-supplied evidence cannot crash the app).
- Total evidence weight below a configurable threshold -> status INSUFFICIENT_EVIDENCE, no ranking.

## Uncertainty
Seeded Monte Carlo weight sensitivity: 1000 runs, each weight x random factor in [0.5, 1.5].
Report leader-stays-leader frequency, mean rank per hypothesis, top-two margin, and a label
"separable" / "not separable" (configurable cut-off, default 70%). A narrow margin must NOT be
reported as a confident attribution.

## State machine (details: docs/state.md)
Max 2 rounds, no infinite loop. Scores only from the Judge. Every claim cites existing IDs.
An unverified source is never shown as confirmed. INSUFFICIENT_EVIDENCE is reachable and tested.
Alert drafts are template-generated from Judge output (no LLM), state that scores are evidence
scores not probabilities, that data is simulated, that no source is confirmed, and cite ledger
IDs. Drafts are NEVER sent; a human approves or rejects.

## Honesty rules
- Data is simulated; weights are expert priors, not fitted; scores are not probabilities;
  evaluation is on simulated scenarios and gives no real-world validation. Say so in README and UI.
- Never invent results. Report counts including misses (e.g. 5/6). Report test failures accurately.
- Ask the human before changing architecture.

## Stack limits (no new dependencies without asking)
Python 3.11; langchain-groq (Groq); Pydantic; Pandas; NumPy; Streamlit; Plotly; pytest;
python-dotenv; requests. LangGraph only for the workflow and only if the state-machine tests pass
within a hard ~10-minute wall-clock budget (one quick retry allowed before fallback), otherwise a
plain Python state machine (describe it accurately in the README). Open-Meteo rainfall tool with a
local cache and a simulated fallback; record which was used. Do not name any package "trace"
(standard-library clash); the project name is "trace-agent".

## Secrets and env
- GROQ_API_KEY and GROQ_MODEL live in .env (git-ignored; .env.example holds placeholders).
  Never print, log, or commit secrets.
- Validate env only when an online call is made; a missing GROQ_MODEL **hard-fails** that call
  with a clear "set GROQ_MODEL" message — no guessed default. `--offline` mode must work with no
  key (cached weather, template hypotheses, deterministic Challenger rules).
- Baseline B1 (single-pass LLM) is online-only: with no key report "skipped (no key)" — never
  fabricate a number — and record the model id whenever it runs.

## Build-day rules (details: docs/steps.md)
- Step sequence S1..S11 with target times; no new architecture after 16:15.
- Cut order when behind: semi-real data, custom-evidence form, extra charts, LangGraph,
  noisy variants, baseline B1.
- NEVER cut: source groups, sensitivity, next-test table, state-machine tests, limitations statement.
