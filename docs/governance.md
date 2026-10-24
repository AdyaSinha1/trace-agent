# Governance (true to the code)

**Purpose and users.** Trace is decision support for a municipal water utility's operations team
handling a simulated water-quality incident. It ranks explanations of an incident, challenges its
own leader, and recommends the next measurement. It is not an autonomous decision-maker.

**Data.** All data is simulated scenario JSON (timestamps, sensor readings, logs). No personal
data is collected or processed.

**Decision process.** The Investigator (LLM only when enabled; templates offline) proposes the
pack's hypotheses with cited evidence IDs. The Challenger (deterministic rules; LLM only when
enabled) receives ONLY the leading hypothesis and the raw ledger and returns contradictions and
missing evidence. The Judge (pure Python, no LLM) computes evidence scores, uncertainty and the
next test. A human approves or rejects every alert draft; only approved flows create simulated
actions.

**Controls (each verified by tests).**
- Citations required: claims citing unknown ledger IDs are rejected (`tests/test_agents.py`).
- Scores are evidence scores, not probabilities, and are labelled so everywhere; only the Judge
  writes scores (`tests/test_workflow.py::test_scores_only_from_the_judge`).
- INSUFFICIENT_EVIDENCE stops the workflow when total weight is below `min_total_weight`
  (`test_missing_data_ends_insufficient`).
- Separability: seeded Monte Carlo labels narrow margins "not separable"; never confident.
- Approval gate: no action executes unless `approval == approved`; rejected flows create nothing
  (`test_no_action_without_approval`, `test_rejected_flow_creates_nothing`).
- Append-only audit ledger: every workflow step is recorded; records are never mutated or deleted.
- `config/policy.json` limits: `max_rounds=2`, `separability_cutoff=0.7`,
  `external_notifications=false`, `allowed_actions` list.
- Nothing is ever sent: notifications stay "DRAFT, NOT SENT"; work orders stay "simulated".
- Offline/LLM-off mode runs with no API key; online calls hard-fail without `GROQ_MODEL`.

**Known limitations and failure modes.** Simulated data only; expert priors are not fitted; wrong
pack rules would mis-sign evidence; correlated sensor failure is not modelled; the next-test
choice is a heuristic, not an optimal design; a missing fourth explanation cannot appear (the
three-hypothesis set is closed). Baseline evaluation is written but NOT run/verified.

**Review and override.** A reviewer reads the Board (why-the-leader-changed diff with evidence
IDs), the Challenger findings, and the append-only ledger; the human approves or rejects the draft
alert on the Approval page; rejection produces a report with no actions.

**Adding a domain safely.** Add a pack (see README); the engine contains no domain logic; the
fake-pack engine test proves Judge/sensitivity/next-test run unchanged on a non-water pack.
