# ClinicalTrials.gov Query-to-Visualization Agent

A backend service that turns natural-language questions about clinical trials into
**structured visualization specifications**, backed by live [ClinicalTrials.gov](https://clinicaltrials.gov/data-api/api)
data.

> **Design principle:** the LLM *plans*; deterministic code *computes*. The model translates a
> question into a validated query plan and never emits a data value — so counts, buckets, and
> citations come from real API records, not the model's imagination.

Full run instructions, schema documentation, and design decisions land here as the build
progresses. See [`DESIGN.md`](DESIGN.md) for the decisions-and-tradeoffs write-up.

## Quick start

```sh
uv sync            # install deps into .venv
just verify        # single green gate: lint + typecheck + tests
just run           # start the API on http://127.0.0.1:8000
```
