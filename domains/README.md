# Domain packs

A domain pack teaches the engine a new incident domain without touching `core/`:

- `pack.json` — hypotheses, evidence types (tier + weight + rationale), relation rules,
  candidate tests (cost + outcome likelihoods + rationale), action templates, thresholds.
- `features.py` — optional pure-Python feature extractors (raw readings -> evidence items),
  registered in the `EXTRACTORS` dict.
- `scenarios/` — simulated incident scenarios (JSON) for this pack.

`domains/it_incident/` is reserved for a second pack (added later).
