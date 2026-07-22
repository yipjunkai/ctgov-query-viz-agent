# Eval harness

Offline stress-test of the planner: generate a gold-labeled question corpus, then score the real
LLM planner against it. Findings write-up: [`docs/EVAL.md`](../../docs/EVAL.md).

Run everything from the repo root (so `ctgov_agent` imports and the test fixture resolve).

## 1. Generate a corpus (free, deterministic)

```sh
uv run python tools/eval/gen_questions.py --n 1000 --out corpus.jsonl
```

Each line is `{id, question, klass, expected_intent, expected_filters}`. `klass` is one of
`supported:*`, `adversarial:*`, `unsupported:*`.

## 2. Tier 0 — validate gold labels + fuzz the spine (free, no LLM, no network)

```sh
uv run python tools/eval/tier0_spine.py corpus.jsonl
```

Confirms every supported gold label constructs a valid `QueryPlan`, and that `build_query_params` and
the viz builders never crash over the corpus.

## 3. Tier 1 — audit the real planner, plan-only (needs an LLM key)

Set `OPENROUTER_API_KEY` or `OPENAI_API_KEY` (see `.env.example`). This calls the model but does **not**
page ClinicalTrials.gov.

```sh
uv run python tools/eval/tier1_planner.py corpus.jsonl tier1_results.jsonl 500
uv run python tools/eval/tier1_report.py tier1_results.jsonl
```

`tier1_report.py` prints intent accuracy, the unsupported refuse-vs-force-fit rate (the acid test),
adversarial handling, and latency percentiles.

To measure a prompt change, keep the first run, edit the prompt, run again to a second file, and diff:

```sh
uv run python tools/eval/tier1_compare.py tier1_results.jsonl tier1b_results.jsonl
```

## 4. Tier 2 — curated live end-to-end (needs a key + a running server)

```sh
just run    # in another shell
uv run python tools/eval/tier2_live.py tier2_results.json
```

Drives 25 hand-picked questions through the full pipeline against live data and checks each response's
status against its expectation.

> Note: Tier 1/2 make real model calls (and Tier 2 hits the public CT.gov API). Keep sample sizes
> modest; the tiers are designed so most signal comes from the cheap plan-only pass.
