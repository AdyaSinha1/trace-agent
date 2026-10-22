# Trace — Scoring, Uncertainty, Next-Test (design contract for S2, S2b, S3)

## Scores are evidence scores, NOT probabilities
Everywhere scores appear (code output, Streamlit UI, README, report) they are labelled
**"evidence scores, not probabilities"**. A score measures how much independent, weighted evidence
supports a hypothesis relative to the other two; it is not a calibrated probability that the
hypothesis is true.

## Formula
- `raw_h = max(0.1, 1.0 + Σ (signed_weight × reliability))` — the sum runs over **independent
  evidence groups**, not raw items.
- Normalisation: `score_h = raw_h / Σ_h' raw_h' × 100` (so the three scores sum to 100).
- Unknown evidence type: weight **0** and a flag — evidence supplied at runtime (judge/user form)
  can never crash the app.
- If **total evidence weight** (sum of |weights| over active evidence) is below a configurable
  threshold → status `INSUFFICIENT_EVIDENCE`, **no ranking emitted**.

## Source groups (correlated observations)
- Every ledger item carries `source_group` (e.g. same sensor/station within the same time window,
  or the same upstream chain inference).
- Within a group, **only the strongest signed weight per hypothesis counts**. Ten readings from
  one downstream sensor cannot count ten times against one hypothesis — the group contributes its
  single strongest signed contribution.
- Groups are computed per (hypothesis, source_group): an item may dominate for one hypothesis and
  not another.

## Weight tiers — expert-assigned priors, NOT fitted to data
These follow structured analysis of competing hypotheses (ACH) practice: a direct, independently
verifiable record outranks a live physical reading, which outranks an inference. They are set by
expert judgement before the build and are **not tuned on the scenarios**.

| Tier | Weight | Examples | Rationale (one line) |
|---|---|---|---|
| **A** | 3 | verified direct record: discharge log, lab sample | direct record of the causal act, independently verifiable |
| **B** | 2 | in-situ sensor reading: pH, dissolved oxygen, turbidity | real-time physical measurement, but noisy and spatially local |
| **C** | 1 | indirect/modelled: rainfall inference, upstream-chain inference | inferred from correlated context; weakest link to the cause |

- **Signs**: a tier's weight is signed per hypothesis (supports = +, contradicts = −) by rules in
  `config/relations.json`. The data files carry RAW observations only — no support/contradict
  labels — so the Challenger genuinely discovers the relations by rule.

## Uncertainty — seeded Monte Carlo weight sensitivity
- 1000 runs; each run multiplies every weight by a random factor in `[0.5, 1.5]` (seeded RNG →
  reproducible results).
- Report: (a) fraction of runs the leader stays leader; (b) mean rank per hypothesis; (c) the
  top-two margin distribution.
- Label: **"separable"** if leader-stays-leader frequency ≥ cut-off (default 70 %, configurable),
  else **"not separable"**.
- A narrow margin is reported as a narrow margin — never as a confident attribution.

## Next-test ranking — heuristic, not exact optimisation
- `config/tests.json` lists candidates (sample storm drain; sample just upstream of outlet; check
  discharge meter log; conductivity; ammonia; recheck turbidity/DO), each with:
  an **assumed outcome likelihood per hypothesis** (with a written rationale) and a **cost**.
- For each test: **expected information gain** computed over the possible outcomes, using the
  current **normalised scores as heuristic weights** over hypotheses (the outcome model is the
  config likelihoods); then **gain per cost**.
- Output: the best test **and the full table**, plus what each possible result would imply — all
  derived from config, nothing hard-coded.
- The LLM may only **rephrase** the explanation of the recommendation.
- Stated plainly in UI and report: this is a **heuristic ranking, not exact optimisation**.

## Limitations
- **Simulated data only.** Six hand-built scenarios and seeded noisy variants; no real-world
  validation is claimed anywhere.
- **Weights are expert priors**, not fitted or calibrated to the data; different expert weights
  could change rankings (the sensitivity analysis partially probes this).
- **Scores are relative** within one scenario at one time — not probabilities, not comparable
  across scenarios, and the normalisation makes the three hypotheses a closed set (a missing
  fourth explanation cannot appear).
- **Monte Carlo perturbs weights only**; it does not model correlated failure of an entire source
  group, systematic sensor bias, or wrong rules in `config/relations.json`.
- **Next-test choice is heuristic** (gain-per-cost on assumed outcome likelihoods), not an optimal
  experiment design; the assumed likelihoods are unvalidated.
- **Attribution ≠ causation proven**: even a "separable" result is evidence-weighted reasoning on
  simulated data, and the system is a decision-support draft for a human, not an autonomous
  decision-maker.
