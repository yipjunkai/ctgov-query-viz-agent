# ClinicalTrials.gov Query-to-Visualization Agent

A backend service that turns natural-language questions about clinical trials into **structured
visualization specifications**, backed by live [ClinicalTrials.gov](https://clinicaltrials.gov/data-api/api)
data.

> **Core principle: the LLM plans; deterministic code computes.** The model translates a question
> into a validated query plan and never emits a data value — so every count, bucket, and citation
> comes from real API records, not the model's imagination. The agent would rather **refuse** than
> answer wrong.

See **[DESIGN.md](DESIGN.md)** for the decisions-and-tradeoffs write-up (the primary document).

## Architecture

```
NL query → [LLM planner] → QueryPlan (intent-discriminated IR) → [guardrails]
        → [executor → CT.gov v2] → [aggregate] → [vizselect] → [citations]
        → { status: ok | refused | needs_clarification, visualization, meta }
```

The LLM appears once, only to produce a plan; retrieval, counting, and visualization are pure
deterministic code. Backend owns all logic; the response schema is a fixed frontend contract.

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

## Demo (optional)

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
- **`refused`** → `{ status, reason, message, detail }` — `reason` ∈ `out_of_domain, too_broad,
  no_data, upstream_error, planner_unavailable, unsupported`.
- **`needs_clarification`** → `{ status, question, detail }` — the query was ambiguous.

The **`visualization`** is itself discriminated on `kind`:

- **`chart`** (`bar_chart`, `histogram`, `time_series`, `grouped_bar`, `choropleth`):
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

Five full request → response examples are in **[`examples/`](examples/)**, regenerable with
`just examples` (needs network).

## Query & visualization coverage

| Question class    | Intent         | Visualization   | Example                                            |
|-------------------|----------------|-----------------|----------------------------------------------------|
| Distribution      | `distribution` | `bar_chart`     | "trials by phase / status / sponsor type"          |
| Time trend        | `time_trend`   | `time_series`   | "trials per year since 2015"                       |
| Comparison        | `comparison`   | `grouped_bar`   | "compare phases for Drug A vs Drug B"               |
| Geographic        | `geographic`   | `choropleth`    | "which countries have the most trials"             |
| Relationship      | `network`      | `network_graph` | "network of sponsors ↔ drugs; drug ↔ drug"         |

All five run through one engine — a new class is a new IR variant + one aggregation + one viz
mapping. (The no-key rule planner covers all but comparison; comparison needs the LLM planner.)

## Testing

```sh
just verify    # ruff (format+lint) + pyright --strict + pytest  (no network)
just e2e       # live smoke against ClinicalTrials.gov + the real LLM (needs key); skips if absent
```

Confidence comes from layered tests, not a coverage %: Hypothesis property tests (the citation
invariant, parser totality), pure-unit tests of the engine, `TestClient` integration tests per
intent with a DI'd fake planner, and negative tests for every refusal path. See DESIGN.md §4.

## Key design decisions & limitations

Full rationale in **[DESIGN.md](DESIGN.md)**. In brief:

- **LLM plans, code computes** — structural anti-hallucination; the model never emits a number.
- **Intent-discriminated IR** — illegal states unrepresentable; breadth without one-off hacks.
- **Vocabulary sourced from the API** — the planner can only pick values the system certifies exist.
- **Client-side aggregation** — the API's facets are global-only (verified), so filtered counts are
  computed from real paged records; a **too-broad guard** refuses rather than sampling.
- **Deep citations** — exact field values, verified as substrings of the source record.

**Main limitations:** no entity resolution (Pembrolizumab ≠ Keytruda ≠ MK-3475); broad queries are
refused rather than approximated; single-shot (no conversation); month-level time granularity and a
visual frontend are out of scope. Production paths for each are in DESIGN.md §2–3 and §5.

## Integrity note (AI tool usage)

- **Tools used:** built with Claude Code (Anthropic) against the OpenRouter/OpenAI APIs for the
  planner at runtime.
- **Designed vs generated:** the architecture and every non-trivial decision in DESIGN.md were
  determined deliberately (the "LLM plans / code computes" thesis, the IR shape, client-side
  aggregation, the citation-verification invariant, the refusal taxonomy). Implementation was
  AI-generated to that design and human-reviewed slice by slice.
- **How correctness was validated:** the API contract was verified by probing the live API *before*
  coding each layer (facet-filtering limits, Essie filter syntax, field names); the executor's query
  strings and the record parser are pinned by tests against real responses; the anti-hallucination
  guarantee is a property test; every slice had to pass `just verify` before commit.

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
