# Contributing

Thanks for your interest. This project is solo-maintained — clear, focused
contributions help most. **Issues and Pull Requests are the only inbound
channels.**

## Quick start

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
git clone https://github.com/yipjunkai/ctgov-query-viz-agent
cd ctgov-query-viz-agent

uv sync            # create .venv and install deps
just verify        # the single green gate: ruff + strict pyright + pytest
just run           # start the API on http://127.0.0.1:8000
```

No API key is required — with no key the service uses the deterministic
rule-based planner. To exercise the LLM planner, copy `.env.example` → `.env`
and set `OPENROUTER_API_KEY` or `OPENAI_API_KEY`.

## Pull request checklist

- [ ] `just verify` is green (ruff format + lint, `pyright --strict`, pytest)
- [ ] Tests added for the change
- [ ] If it touches a **parser or guardrail**: a property test asserting the
      invariant (e.g. every citation excerpt ⊂ its source record; the parser
      stays total), following the existing `tests/property/` style
- [ ] If it touches **planning / refusal**: a negative test asserting the agent
      *refuses* rather than answering wrong — this is the project's core
      anti-hallucination property (see `tests/e2e/test_refusal_guard.py`)
- [ ] Imperative, capitalized commit subjects that describe the outcome (this
      repo does not use Conventional Commits or release automation)

## Design guardrails

- **The LLM plans; deterministic code computes.** The model may only produce a
  validated `QueryPlan`; every count, bucket, and citation is computed in code
  from real records. Keep the LLM out of the value path.
- **Refuse rather than answer wrong.** A query that can't be mapped is a typed
  refusal, not a guess. New failure modes get a refusal path + a test.
- **Source facts from the API, not the model.** Controlled vocabulary and field
  mappings are pinned against the live ClinicalTrials.gov API, not model memory.

## Style

- Python formatted and linted with `ruff` (line length 100), type-checked under
  `pyright --strict`. The `tools/eval/` analysis scripts are held to a lighter
  bar (excluded from the strict gate).
- One concern per commit; thin vertical slices.

## Before large PRs

For anything beyond a bug fix or small feature, please open an issue first to
check scope alignment — the maintenance budget is finite.
