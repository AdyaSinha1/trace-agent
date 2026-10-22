# Trace — Workflow State Model (implement at S7; this doc is the contract)

Plain-Python or LangGraph state machine is decided at S7. LangGraph gets a hard **10-minute
wall-clock budget** to make the state-machine tests pass; **one quick retry is allowed** (so a
trivial typo doesn't force the fallback), then fall back to plain Python. The README states which
one was used.

## State (Pydantic)

| Field | Type | Notes |
|---|---|---|
| `scenario_id` | `str` | which `scenarios/*.json` is loaded |
| `round` | `int` (0–2) | increments only on evidence injection; hard cap 2 |
| `ledger` | `EvidenceLedger` | append-only evidence store |
| `hypotheses` | `list[Hypothesis]` | the 3 fixed hypotheses, each with cited evidence IDs |
| `leader` | `str \| None` | set ONLY by the Judge |
| `challenger_findings` | `list[Finding]` | contradictions + missing evidence from the Challenger |
| `ranking_history` | `list[RankingSnapshot]` | one snapshot appended per Judge run |
| `sensitivity` | `SensitivityResult` | Monte Carlo result for the current ranking |
| `next_test` | `NextTestRecommendation` | best test + full table |
| `status` | `Status` enum | current workflow status |
| `alert_draft` | `AlertDraft \| None` | drafts only; NEVER sent |
| `approval` | `none \| pending \| approved \| rejected` | human decision on the draft alert |

## Statuses
`INIT`, `INVESTIGATING`, `CHALLENGING`, `JUDGING`, `INSUFFICIENT_EVIDENCE`, `DONE`, `AWAITING_EVIDENCE`

## Transitions

- `INIT -> INVESTIGATING`: scenario loaded, initial evidence appended to the ledger.
- `INVESTIGATING -> CHALLENGING`: hypotheses valid (exactly the 3 fixed names) and every cited
  evidence ID resolves in the ledger. On LLM failure: fall back to template hypotheses and record
  the fallback in the ledger (an `agent_claim` entry noting template use).
- `CHALLENGING -> JUDGING`: deterministic rules run first; then LLM findings are validated —
  citations must resolve to existing IDs, otherwise the finding is dropped.
- `JUDGING -> INSUFFICIENT_EVIDENCE`: total evidence weight below the configurable threshold;
  no ranking is emitted.
- `JUDGING -> DONE`: leader stable AND sensitivity label is "separable", or round == 2.
- `JUDGING -> AWAITING_EVIDENCE`: otherwise; the next-test table is shown.
- `AWAITING_EVIDENCE -> INVESTIGATING`: new evidence injected via the UI button → ledger append
  (kind = `injected`), round + 1, full re-run.
- `DONE -> approval = pending`: when an alert draft is requested. The draft is **template-generated
  from the Judge output — no LLM involved**. The template must state: these are evidence scores and
  not probabilities; the data is simulated; no source is confirmed. It cites the ledger IDs that
  support it. Alerts are drafts only and are **NEVER sent**; a human approves or rejects.
  Terminal states do not loop.

## Ranking snapshots
Every Judge run appends a `RankingSnapshot`: per-hypothesis evidence scores, leader, the evidence
IDs (and groups) that contributed, and the signs of their contributions.
**"Why the leader changed" = the diff between the last two snapshots**: evidence added since the
previous run, group-dominance changes (a different item now dominates a source group), sign flips
from Challenger-confirmed contradictions, and the resulting score deltas. The UI renders this diff
verbatim from the snapshots — nothing hand-written.

## Invariants (each gets a pytest test)
1. **Max 2 rounds, no infinite loop.** Any transition sequence terminates; round never exceeds 2.
2. **Scores only from the Judge.** No other component writes scores or ranking fields.
3. **Citation validity.** Every claim (`agent_claim`) cites only ledger IDs that exist at citation
   time; outputs citing unknown IDs are rejected, not stored.
4. **Unverified ≠ confirmed.** An item with `reliability = 0.5` is never displayed as confirmed
   anywhere in the UI or reports.
5. **INSUFFICIENT_EVIDENCE is reachable.** The missing-data scenario triggers it end-to-end.
6. **Challenger purity.** The Challenger never outputs a conclusion and never touches scores; it
   sees only the leading hypothesis + raw ledger, never the Investigator's reasoning.
7. **LLM never scores.** The LLM never sets or edits a score; unknown evidence types get weight 0
   and a flag.
8. **Append-only ledger.** Once appended, a record can never be mutated or deleted.

## Termination and loop safety
- Round cap 2 + status enum means the machine has a bounded state space on the happy path.
- LLM calls are always wrapped: failure → deterministic/template fallback, recorded in the ledger;
  the machine never blocks waiting on an LLM.
