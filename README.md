# ClinicalTrials.gov Query-to-Visualization Agent

A backend service that turns natural-language questions about clinical trials into **structured
visualization specifications**, backed by live [ClinicalTrials.gov](https://clinicaltrials.gov/data-api/api)
data.

> **Core principle: the LLM plans; deterministic code computes.** The model translates a question
> into a validated query plan and never emits a data value — so every count, bucket, and citation
> comes from real API records, not the model's imagination. The agent would rather **refuse** than
> answer wrong.

This README is the full write-up: how to run it, the request/response contract, and — the part that
matters most — **every non-trivial design decision, what it costs, and the production path** I'd take
with more time. The interesting part of a system isn't that it works; it's knowing exactly where it
stops working and what you'd do next.

## Table of contents

1. [Architecture](#architecture)
2. [Quick start](#quick-start)
3. [Demo](#demo)
4. [Request schema](#request-schema)
5. [Response schema](#response-schema)
6. [Query & visualization coverage](#query--visualization-coverage)
7. [Design decisions, costs, and production paths](#design-decisions-costs-and-production-paths)
8. [The biggest scope cut: entity resolution](#the-biggest-scope-cut-entity-resolution)
9. [Testing](#testing)
10. [What I'd do next](#what-id-do-next)
11. [AI tool usage (integrity note)](#ai-tool-usage-integrity-note)
12. [Project structure](#project-structure)

## Architecture

The scoring for this kind of system weights system design and agent design far above raw code, and
the one hard requirement is *don't hallucinate — it's fine to say a query can't be processed*. Both
point to a single idea:

> The LLM is confined to **translating** a question into a validated **query plan**. It never sees a
> record, never emits a count, never writes a citation. Every number in the output is computed by
> deterministic code from real ClinicalTrials.gov records.

The model *cannot* fabricate a trial count because it never produces one. This turns
"don't hallucinate" from a prompt-engineering hope into a structural property.

```
NL query (+ optional structured fields)
  │
  ▼  LLM planner ── OpenAI-compatible, tool-calling, Pydantic-validated
QueryPlan (intent-discriminated IR)
  │
  ▼  guardrails ── unmappable / out-of-domain / too-broad → typed refusal
  ▼  executor   ── IR filters → CT.gov v2 query params (verified Essie syntax)
  ▼  client     ── count() pre-check, then page all matches (pageToken @ 1000)
  ▼  aggregate  ── deterministic group / bucket / co-occurrence  (pure, Counter-based)
  ▼  vizselect  ── (intent, shape) → visualization type + encoding
  ▼  citations  ── attach + verify exact-value excerpts
  │
  ▼
{ status: ok | refused | needs_clarification, visualization, meta }
```

The LLM appears once, at the top; everything after is pure, testable code. That is the seam the
whole design is organized around: **backend owns all logic, the LLM is a thin adapter at the
boundary, and the response schema is a fixed contract.**

## Quick start

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.12+.

```sh
uv sync                      # create .venv and install deps
just verify                  # single green gate: ruff + strict pyright + tests
just run                     # start the API on http://127.0.0.1:8000
```

**Zero-setup:** with no API key configured the service uses a deterministic rule-based planner, so
it runs with no secrets. To use the LLM planner, copy `.env.example` → `.env` and set a key:

```sh
cp .env.example .env         # then set OPENROUTER_API_KEY (preferred) or OPENAI_API_KEY
```

Try it:

```sh
curl -s localhost:8000/visualize -H 'content-type: application/json' \
  -d '{"query": "How are melanoma trials distributed across phases?", "condition": "melanoma"}' | jq
```

## Demo

`just run`, then open **http://127.0.0.1:8000/** for a self-contained page: type a question (or click
an example chip), and it renders the response — charts via **Vega-Lite**, the network via a **Vega
force-directed** graph — plus the response metadata and the deep-citation table. It's a pure consumer
of the `/visualize` contract (no backend rendering logic), which is itself the proof the schema is
frontend-friendly. The page loads Vega from a CDN, so it needs internet for the rendering libs (the
API and data path don't).

## Request schema

`POST /visualize` — `query` is required; the optional structured fields, when supplied,
**deterministically override** the planner (explicit user input never depends on the LLM).

| Field        | Type       | Required | Notes                                                     |
|--------------|------------|----------|-----------------------------------------------------------|
| `query`      | string     | yes      | The natural-language question.                            |
| `drug_name`  | string     | no       | Intervention filter (`query.intr`).                       |
| `condition`  | string     | no       | Condition / disease (`query.cond`).                       |
| `sponsor`    | string     | no       | Lead sponsor name (`query.spons`).                        |
| `phase`      | string[]   | no       | Enum: `NA, EARLY_PHASE1, PHASE1, PHASE2, PHASE3, PHASE4`. |
| `country`    | string     | no       | Location country (`query.locn`).                          |
| `start_year` | integer    | no       | Earliest trial start year.                                |
| `end_year`   | integer    | no       | Latest trial start year.                                  |

## Response schema

Every response is a discriminated union on `status`:

- **`ok`** → `{ status, visualization, meta }`
- **`refused`** → `{ status, reason, message, detail }` — `reason` ∈ `out_of_domain, unsupported,
  too_broad, no_data, upstream_error, planner_failed`.
- **`needs_clarification`** → `{ status, question, detail }` — the query was ambiguous.

The **`visualization`** is itself discriminated on `kind`:

- **`chart`** (`bar_chart`, `time_series`, `grouped_bar`, `choropleth`):
  `{ kind, type, title, encoding: {x, y, series?}, data: [DataPoint] }`
  where `DataPoint = { key, label, value, series?, citations: [Citation] }`.
- **`network`** (`network_graph`):
  `{ kind, type, title, encoding: NetworkEncoding, nodes: [Node], edges: [Edge] }`
  where `Node = { id, label, kind, value }` and `Edge = { source, target, weight, citations }`.

**`Citation` = `{ nct_id, excerpt, field }`** — `excerpt` is the exact value from `field` that
supports the datum, and is a verified substring of the source record.

**`meta`** = `{ source, total_trials_matched, trials_aggregated, filters_applied,
query_interpretation, units, sort, assumptions, truncated }`.

Example `ok` response (trimmed):

```json
{
  "status": "ok",
  "visualization": {
    "kind": "chart", "type": "bar_chart", "title": "Trials by Phase in melanoma",
    "encoding": { "x": {"field": "key", "label": "Phase"},
                  "y": {"field": "value", "label": "Trial count"} },
    "data": [
      { "key": "PHASE2", "label": "Phase 2", "value": 1528, "series": null,
        "citations": [ {"nct_id": "NCT04...", "excerpt": "PHASE2", "field": "phase"} ] }
    ]
  },
  "meta": {
    "source": "clinicaltrials.gov", "total_trials_matched": 3736, "trials_aggregated": 3736,
    "filters_applied": {"condition": "melanoma"}, "sort": "canonical phase order", "truncated": false
  }
}
```

Six full request → response examples are in **[`examples/`](examples/)**; the five deterministic ones
regenerate with `just examples` (the comparison example needs an LLM key, since only the LLM planner
splits a comparison into series).

## Query & visualization coverage

| Question class    | Intent         | Visualization   | Example                                            |
|-------------------|----------------|-----------------|----------------------------------------------------|
| Distribution      | `distribution` | `bar_chart`     | "trials by phase / status / sponsor type"          |
| Time trend        | `time_trend`   | `time_series`   | "trials per year since 2015"                       |
| Comparison        | `comparison`   | `grouped_bar`   | "compare phases for Drug A vs Drug B"              |
| Geographic        | `geographic`   | `choropleth`    | "which countries have the most trials"             |
| Relationship      | `network`      | `network_graph` | "network of sponsors ↔ drugs; drug ↔ drug"         |

All five run through one engine — a new class is a new IR variant + one aggregation + one viz
mapping. (The no-key rule planner covers all but comparison; comparison needs the LLM planner.)

## Design decisions, costs, and production paths

This section states every non-trivial decision, what it costs, and the production path I'd take with
more time.

### Intent-discriminated IR

`planner/ir.py`. The plan is a Pydantic discriminated union —
`distribution | time_trend | comparison | geographic | network` — over a shared `Filters` block.
Modeling it this way makes illegal states unrepresentable: a `NetworkPlan` *must* carry an entity
pair, a `DistributionPlan` *must* carry a categorical dimension, and neither can hold the other's
fields (`extra="forbid"`). *Alternatives rejected:* a flat plan with all-optional fields (illegal
states become representable, policed by validators) and a fully generic query grammar (elegant, but
a looser target for the LLM and weaker anti-hallucination). *Cost:* more schema surface. *Why it's
right here:* the narrowest possible target for the model, and adding a query class is purely
additive — new variant + one executor branch + one viz mapping, no changes to existing code. That is
the "cover many query types with one coherent approach, no one-off hacks" the brief asks for.

### Controlled vocabulary sourced from the API itself

`vocab/`. The enum values the planner may use for `phase`, `status`, `study_type`, `sponsor_class`,
`intervention_type` are pulled from the API's own `/stats/field/values` endpoint, snapshotted, and
enforced by a drift test. The model can only choose filter values the system certifies exist.
*Cost:* the snapshot can drift from the live API. *Production path:* refresh it in CI on a schedule
and fail the build on drift (the test already exists; only the cron is missing).

### Filtered aggregation is client-side — by necessity

I probed the API before designing: `/stats/field/values` returns real server-side facet counts but
is **global-only** — it rejects a query filter with `400`. So counts for any *filtered* question must
be computed from real records. The engine pages every matching study (`pageSize=1000` + `pageToken`)
with a compact field projection and counts in code. *Cost:* a broad query means many pages.
*Mitigations shipped:* a `count()` pre-flight, a too-broad refusal (below), and an on-disk response
cache. *Production path:* periodically ingest ClinicalTrials.gov into a columnar store and aggregate
there — turning O(pages) per query into a single indexed scan.

### Two-tool planner with validate-and-retry

`planner/llm.py`. The model is given exactly two tools — `emit_query_plan` (parameters = the
QueryPlan JSON Schema) and `cannot_answer` — and told to call one. Its raw arguments always run
through Pydantic `parse_plan`; on failure the validation error is fed back for one retry; if it still
fails, we refuse. *Cost:* up to one extra model call. *Production path:* self-consistency (sample N
plans, take the majority) to cut the residual mis-plan rate; per-model structured-output tuning on
OpenRouter.

### Provider strategy + a no-key fallback

`planner/factory.py`, `planner/rules.py`. OpenRouter is preferred, the OpenAI key is an automatic
fallback (both via one OpenAI-compatible client), and when *no* key is present a deterministic
rule-based planner keeps the service running from the structured request fields. *Cost:* the fallback
does no free-text entity extraction and can't split comparisons — it refuses those. *Why:*
clone-and-run with zero secrets, which is how the example runs and much of the test suite stay
reproducible. *Production path:* a small local model for the offline path.

### Uniform data points

`api/schemas.py`. Every chart datum is `{key, label, value, series?, citations}` regardless of
dimension, with `encoding` carrying the human axis labels. *Alternative rejected:* semantic per-query
field names (`{"phase": …, "trial_count": …}`) — self-describing, but forces the renderer to discover
field names dynamically. *Cost:* one layer of indirection through `encoding`. *Why:* a frontend
implements one renderer, not one per query type.

### Deep citations as exact, verifiable values

`engine/citations.py`. Each datum/edge carries contributing `nct_id`s and an `excerpt` that is the
*exact* field value that placed the record in that bucket — which makes it a provable substring of
the source record. A property test enforces *every excerpt occurs in its source record*. *Cost:*
excerpts are terse (`"PHASE3"`, a country name, a trial title for edges) rather than free prose.
*Why:* an unverifiable prose snippet is exactly the hallucination surface we're eliminating.
*Production path:* character-span provenance into specific API fields, and a richer NL excerpt that is
still span-checked.

### Refusal is a first-class, typed outcome

The response is a discriminated union on `status`; `refused` (out-of-domain, too-broad, no-data,
upstream-error) and `needs_clarification` (ambiguous) are real states, not errors. The too-broad
guard refuses rather than silently sampling a set too large to count exactly. *Cost:* some
legitimately broad questions get bounced back for narrowing. *Why:* it's the brief's "cannot be
processed rather than wrong" made mechanical, and it's tested.

### No database

The data source is the external API plus a response cache; there's no ORM or Postgres. *Cost:*
latency and rate-limit exposure on broad queries. *Why:* a DB would be scope-inflation for a
read-through visualization service. *Production path:* the ingestion store above (which also removes
the too-broad limitation).

## The biggest scope cut: entity resolution

Drug and condition names are passed to ClinicalTrials.gov's search as-is. There is **no synonym /
ontology layer**, so *Pembrolizumab*, *Keytruda*, and *MK-3475* are three different queries. This is
the limitation most likely to surprise a user. *Production path:* normalize entities through RxNorm /
MeSH / ChEMBL before building filters, and expose the resolved entity in `meta` so the user sees what
was actually queried.

## Testing

```sh
just verify    # ruff (format+lint) + pyright --strict + pytest  (no network)
just e2e       # live smoke against ClinicalTrials.gov + the real LLM (needs key); skips if absent
```

Confidence comes from layered tests behind one gate (`just verify` = ruff + strict pyright +
pytest), not a coverage number:

- **Property (Hypothesis):** the citation invariant (*every excerpt ⊂ its source record*) and record
  parser totality (*never raises on any input shape*).
- **Unit:** the pure engine — executor param-building (strings verified against the live API),
  aggregation counting (multi-value membership, per-study dedupe), network edge weights, IR
  validation (every rejection case).
- **Integration (`TestClient` + DI'd fake planner + mocked API):** each intent end-to-end to an exact
  visualization spec, and every refusal path.
- **Negative:** out-of-domain → refused, too-broad → refused *without paging*, malformed LLM output →
  retried then refused, upstream 500 → refused.
- **Live smoke (`just e2e`, network-gated):** proves the CT.gov field mappings and the real LLM
  tool-calling path still hold; skipped cleanly when no key is set.

Beyond the suite, an offline **planner stress-test** (a gold-labeled question corpus scored against
the real planner) measures mis-plan and refuse-vs-force-fit rates — see [`docs/EVAL.md`](docs/EVAL.md)
and [`tools/eval/`](tools/eval).

## What I'd do next

In priority order:

1. **Entity resolution** via a medical ontology — the highest-leverage correctness win.
2. **Ingestion store** for aggregation — removes the too-broad limit and the paging cost.
3. **Self-consistency planning** — sample multiple plans and vote, to drive the mis-plan rate down.
4. **Richer, still-verified citations** — character spans and NL excerpts checked against source.
5. **More intents** — funnel/sankey for enrollment, survival-style timelines — each additive.
6. **A thin renderer** — ship the Vega-Lite adapter + a real frontend so the specs are seen, not
   just described.

## AI tool usage (integrity note)

An honest account of how AI tooling was used, per the assignment's integrity requirement.

**Tools used:** built with Claude Code (Anthropic). The planner calls the OpenRouter/OpenAI APIs at
runtime; that is separate from the tooling used to write the code.

**How it was built:** implemented against a design decided deliberately, up front, through
discussion. The workflow was **thin vertical slices** — each slice (scaffold → IR → client → one
intent → planner → more intents → network → citations → guardrails → examples → docs) had to pass
`just verify` (ruff + strict pyright + pytest) before it was committed.

**Designed vs generated:** the architecture and every non-trivial decision above were determined
deliberately (the "LLM plans / code computes" thesis, the IR shape, client-side aggregation, the
citation-verification invariant, the refusal taxonomy). Implementation was AI-generated to that
design and human-reviewed slice by slice.

| Area                                    | Design / decision         | Implementation | Verified by                              |
|-----------------------------------------|---------------------------|----------------|------------------------------------------|
| "LLM plans, code computes" thesis       | Human                     | AI             | Whole architecture; citation invariant   |
| Intent-discriminated IR shape           | Human (chosen over 2 alt) | AI             | `test_ir.py` (all rejection cases)       |
| Client-side aggregation strategy        | Human (from API probing)  | AI             | Live API probes + `test_ctgov_client.py` |
| CT.gov query/filter syntax              | Verified vs live API      | AI             | Probes, then `test_executor.py`, e2e     |
| Vocabulary-from-API guardrail           | Human                     | AI             | `test_vocab.py` drift guard              |
| Deep-citation verification invariant    | Human                     | AI             | `test_citations_invariant.py` (property) |
| Refusal taxonomy (`ok/refused/clarify`) | Human                     | AI             | `test_guardrails.py`                     |
| Prompt + tool definitions               | Human intent, AI drafted  | AI             | `test_llm_planner.py` (DI fake model)    |
| Test suite                              | Human (test philosophy)   | AI             | It is the verification                   |

**Guardrails against trusting model memory.** API facts were **never taken from the model's memory**.
Before writing each layer I probed the live ClinicalTrials.gov v2 API and used the actual responses:

- Confirmed `/stats/field/values` is global-only (rejects query filters) — this decided the whole
  aggregation strategy.
- Captured the exact controlled vocabulary (phases, statuses, sponsor classes, …) into a committed
  snapshot with a drift test.
- Verified the Essie `filter.advanced` syntax (`AREA[Field](A OR B)`, `RANGE[lo,hi]`) and the
  projection field names against real 200 responses, then pinned them with tests.

**Adversarial review.** Findings and code were checked from independent angles rather than a single
read: correctness (does the count conserve? does the parser stay total?), anti-hallucination (can any
excerpt fail to appear in its source?), and real-world-data handling (missing fields, multi-value
fields, empty results, too-broad sets). Each concern is encoded as a test so it stays checked, not
checked once.

## Project structure

```
src/ctgov_agent/
├── api/         # FastAPI app (thin) + request/response schemas
├── planner/     # QueryPlan IR, LLM planner (+ validate/retry), rule fallback, prompt
├── vocab/       # controlled vocabulary sourced from /stats/field/values (+ snapshot)
├── ctgov/       # v2 API client (paging, projection, cache) + defensive record parser
└── engine/      # executor · aggregate · network · vizselect · citations · pipeline
tests/           # unit · integration · property · e2e   (single gate: just verify)
examples/        # 3–5 golden request→response runs
```

## License

MIT — see [`LICENSE`](LICENSE).
