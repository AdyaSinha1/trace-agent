# Trace (`trace-agent`)

An investigator that tries to prove itself wrong: for a simulated incident it ranks three
competing explanations, challenges its own leader against raw evidence, re-ranks when new
evidence arrives (explaining why), and recommends the next measurement that best separates
the remaining explanations.

**Status: Step 1 skeleton.** Config-driven, domain-agnostic engine; scoring, agents and
workflow land in later steps. Three agents share one append-only evidence ledger — no fourth
agent, and the LLM never sets a score.

## Run (offline — no API key needed)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python cli.py --offline      # CLI smoke run
.venv\Scripts\streamlit run app.py         # dashboard skeleton
.venv\Scripts\python -m pytest             # tests
```

## Online LLM (optional)

Copy `.env.example` to `.env`, then set `GROQ_API_KEY` and `GROQ_MODEL`. There is **no guessed
default**: an online call without `GROQ_MODEL` hard-fails with a clear message. `--offline`
mode always works with no key.

## Honesty / limitations

All data is simulated. Weights are expert-assigned priors, not fitted. Scores are **evidence
scores, not probabilities**. Evaluation runs on simulated scenarios and gives no real-world
validation. Nothing is ever sent — alerts are drafts awaiting human approval. See `docs/`.
