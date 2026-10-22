# Trace — Decision log

Human-answered clarifications. Each is binding unless the human changes it.

## Step 0 (22 Oct 2026)

1. **Next-test metric.** Primary ranking metric: **expected entropy reduction** over the
   normalised-score distribution (standard, principled choice). The **expected change in the
   top-two margin** is shown as an extra column in the table (easier to explain to judges). Both
   are heuristic — scores are not calibrated — so the "heuristic ranking" note stays.
   Constraint: the rainfall-reversal scenario must still recommend the storm-drain or upstream
   sample (enforced via config likelihoods, not hard-coding). → `docs/scoring.md`

2. **B1 baseline with no key.** Report **"skipped (no key)"** in the evaluation table and the
   README. Never fabricate a number. Record the model id whenever B1 does run. → `docs/steps.md` S9

3. **GROQ_MODEL default.** **Hard-fail** online calls with a clear message telling the user to set
   GROQ_MODEL. Do not guess a default (model names change; the deck references a verified model
   id). `.env.example` holds a placeholder. Offline mode still works with no key. → `AGENTS.md`

4. **Alert draft.** Template-generated from the Judge output, **no LLM involved**; a human only
   approves or rejects. The template states: these are evidence scores and not probabilities; the
   data is simulated; no source is confirmed. It cites the ledger IDs. Nothing is ever sent.
   → `docs/state.md`

5. **LangGraph.** Confirmed with a **hard 10-minute wall-clock budget**. If the state-machine tests
   are not passing on LangGraph within that time, fall back to plain Python — **one quick retry
   allowed first** so a trivial typo doesn't force it. The README says which one was used.
   → `docs/state.md`, `docs/steps.md` S7
