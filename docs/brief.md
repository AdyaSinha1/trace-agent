# Trace — Project Brief (verbatim, Step 0)

Below is the hackathon brief exactly as given by the human on Step 0 (22 Oct 2026). It is the
source of truth; AGENTS.md is its condensed working version.

---

You are my coding partner for a seven-hour solo hackathon build: AgentOps'26, MIT Bengaluru,
24 Oct 2026. Build window 11:00-17:00, lunch about 13:30-15:00 (tentative), final submission
17:00. Everything is built from scratch in this empty folder. Work in small steps, commit after
each step, and STOP after each step until I say "go step N".

THIS MESSAGE IS STEP 0 ONLY: write documentation and rules. Write NO application code.

== PROJECT ==
Trace: "an investigator that tries to prove itself wrong". For a simulated water-pollution
incident it ranks three competing explanations (factory_discharge, storm_runoff,
upstream_source), challenges its own leading explanation using raw evidence, re-ranks when new
evidence arrives and explains why, and recommends the next measurement that best separates the
remaining explanations. Track: Agents for Sustainable Development (SDG 6).
An evaluator recommended it for selection on the condition that it shows scientifically
defensible attribution and measurable improvement over baselines. Build for that.

== ARCHITECTURE (matches the submitted deck; do not change) ==
Three agents sharing one append-only evidence ledger. There is NO fourth agent.
1. Investigator (LLM + Python tools): reads records, detects anomalies with deterministic
   Python, proposes the three hypotheses with supporting evidence IDs.
2. Challenger (deterministic rules first, then LLM): receives ONLY the leading hypothesis and
   the raw ledger evidence, never the Investigator's reasoning. Returns contradictions and
   missing evidence. It never states a conclusion and never touches scores.
3. Judge (pure Python, NO LLM): applies weights, re-ranks, explains what changed, estimates
   uncertainty, and chooses the next test.
The LLM (Groq, Llama, model id from env GROQ_MODEL) never sets or edits a score.

== EVIDENCE LEDGER ==
Append-only. Fields: id, source, source_group, timestamp, location, observation, kind
(observation | tool_output | agent_claim | injected), reliability (verified 1.0 | unverified 0.5).
Every claim by any agent must cite existing ledger IDs; reject output citing unknown IDs.
The data stores RAW observations only. Supports/contradicts relations come from rules in
config/relations.json, not from hand labels in the data, so the Challenger genuinely discovers
contradictions. Ground truth lives only in tests/fixtures; agents never read it.

== SCORING (document in docs/scoring.md) ==
- raw_h = max(0.1, 1.0 + sum(signed_weight x reliability)) over independent evidence groups;
  normalise to 100. Scores are evidence scores, NOT probabilities; label them so everywhere.
- Weights by tier with a one-line rationale each: A = verified direct record
  (discharge log, lab sample) = 3; B = in-situ sensor reading = 2; C = indirect or modelled
  (e.g. rainfall inference) = 1. State plainly these are expert-assigned priors from
  structured-analysis practice (Analysis of Competing Hypotheses), NOT fitted to data.
- Correlated observations: each item has a source_group (same sensor/station and time window, or
  same upstream chain). Within a group only the strongest signed weight per hypothesis counts.
- Unknown evidence type = weight 0, flagged (so judge-supplied evidence cannot crash the app).
- If total evidence weight is below a configurable threshold: status INSUFFICIENT_EVIDENCE, no ranking.

== UNCERTAINTY ==
Seeded Monte Carlo weight sensitivity: 1000 runs, each weight x random factor in [0.5, 1.5].
Report how often the leader stays the leader, mean rank per hypothesis, top-two margin, and a label
"separable" or "not separable" (configurable cut-off, default 70%). A narrow margin must NOT be
reported as a confident attribution.

== NEXT TEST ==
config/tests.json: candidate tests (sample storm drain, sample just upstream of outlet, check
discharge meter log, conductivity, ammonia, recheck turbidity/DO), each with an assumed outcome
likelihood per hypothesis (with rationale) and a cost. For each test compute expected information
gain, using the normalised scores as heuristic weights, then gain per cost. Return the best test
AND the full table, and what each possible result would imply, all derived from config. The LLM
may only rephrase the explanation. State it is a heuristic ranking, not exact optimisation.

== WORKFLOW STATE MODEL (write docs/state.md; implement later) ==
State (Pydantic): scenario_id, round (0-2), ledger, hypotheses, leader, challenger_findings,
ranking_history (one snapshot per Judge run), sensitivity, next_test, status, alert_draft,
approval (none|pending|approved|rejected).
Transitions:
 INIT -> INVESTIGATING (scenario loaded, initial evidence appended)
 INVESTIGATING -> CHALLENGING (valid hypotheses, valid citations); on LLM failure use templates
   and record it in the ledger
 CHALLENGING -> JUDGING (rules first, then LLM findings validated)
 JUDGING -> INSUFFICIENT_EVIDENCE (weight below threshold) | DONE (leader stable and separable,
   or round = 2) | AWAITING_EVIDENCE (otherwise; next test shown)
 AWAITING_EVIDENCE -> INVESTIGATING (new evidence injected; ledger append; round + 1)
 DONE -> approval = pending when an alert draft is requested. Alerts are drafts only and are
   NEVER sent; a human approves or rejects.
Invariants (each gets a test): max 2 rounds and no infinite loop; scores only from the Judge;
every claim cites existing IDs; an unverified source is never shown as confirmed;
INSUFFICIENT_EVIDENCE is reachable.
Each Judge run appends a ranking snapshot; "why the leader changed" is the diff between snapshots.

== SCENARIOS (all simulated and labelled so) ==
Six hand-built scenarios in scenarios/*.json: 2 clear (one factory, one runoff), 2 ambiguous,
1 rainfall reversal (factory looks guilty until heavy rainfall + upstream pollution arrive; this is
the demo), 1 missing-data failure (must stop with INSUFFICIENT_EVIDENCE). Each has timestamped
upstream/downstream pH, dissolved oxygen, turbidity, a discharge log, rainfall, incident
timestamps, initial evidence, and injected evidence. A seeded generator makes noisy variants
(sensor noise, small time shifts). The demo must show the leader changing because of real
rule-derived evidence; do NOT hard-code the illustrative numbers (62/18/20 -> 24/46/30) on the
deck slide.

== BASELINES AND EVALUATION ==
Compare on the same scenarios: Trace full; B2 Investigator-only (no Challenger, no re-assessment);
B3 simple rule (downstream exceeds upstream and a discharge is logged -> factory); B1 single-pass
LLM given all evidence in one prompt (online only). Metrics: correct attribution after all
evidence; ranking revised in the right direction after new evidence (target at least 5 of 6);
next test separates the top two hypotheses (target at least 5 of 6); next-test effectiveness
(simulate each test's outcome from ground truth; compare recommended vs random vs cheapest test);
leader stability; 100% citation validity. Report counts (e.g. 5/6), include misses. Variants are
perturbations of 6 cases, not independent cases. Never invent results.

== STACK ==
Python 3.11; Groq via langchain-groq; Pydantic; Pandas; NumPy; Streamlit; Plotly; pytest;
python-dotenv; requests. LangGraph for the workflow ONLY if it works within about 10 minutes,
otherwise a plain Python state machine (and describe it accurately). Open-Meteo rainfall tool with
a local cache and a simulated fallback; record which was used. Do not add other dependencies
without asking. Do not name any package "trace" (standard-library clash); project name "trace-agent".

== CONFIG / ENV ==
GROQ_API_KEY and GROQ_MODEL from .env (git-ignored; never print or commit secrets). Validate env
only when an online call is made. --offline mode must work with no key (cached weather, template
hypotheses, deterministic Challenger rules).

== UI (Streamlit, built later) ==
Scenario selector; ranked evidence scores; Challenger findings; supporting and contradicting
evidence; evidence ledger with IDs; before/after ranking and "why the leader changed";
uncertainty warning; "Inject new evidence" button; next-test table; Reliability panel (weight table
with rationale, sensitivity result, full next-test table); human-approval panel for draft alerts.
Label scores "evidence scores, not probabilities". No auth, database or animation.

== STEP SEQUENCE (target times; no new architecture after 16:15) ==
S1 11:00 foundation and skeleton | S2 11:20 scenarios, ledger, Judge with groups | S2b
sensitivity | S3 12:25 next-test table | S4 minimal dashboard | S5 13:00 Investigator (templates
first) | lunch | S6 15:00 Challenger | S7 15:40 workflow and state machine, injection | CUT LINE
16:15: if the Challenger is not reliable, demo Judge re-ranking on injected evidence and say so |
S8 Reliability panel and dashboard finish | S9 evaluation and baselines | S10 audit | S11 README,
demo script, submission. Optional only if on schedule: semi-real data, custom-evidence form,
Ollama. Cut order when behind: semi-real data, custom-evidence form, extra charts, LangGraph,
noisy variants, baseline B1. NEVER cut: source groups, sensitivity, next-test table, state-machine
tests, limitations statement.

== HONESTY RULES ==
Data is simulated; weights are expert priors, not fitted; scores are not probabilities; evaluation
is on simulated scenarios and gives no real-world validation. Say so in the README and UI. Report
test results accurately, including failures. Ask me before changing architecture.

== STEP 0 DELIVERABLES (do these now, then stop) ==
1. AGENTS.md: a condensed version of the rules above (design rules, invariants, honesty rules,
   stack limits, never-commit-secrets).
2. docs/brief.md: this brief, verbatim.
3. docs/state.md: the state model and invariants.
4. docs/scoring.md: formula, tiers with rationale, source groups, sensitivity method, and a
   "Limitations" section.
5. docs/steps.md: the step sequence with a "done when" line for each step.
Then print a summary of at most 15 lines, list any ambiguities as questions, and STOP.
