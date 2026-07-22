# ClinicalTrials.gov Query-to-Visualization Agent

[![CI](https://github.com/yipjunkai/ctgov-query-viz-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/yipjunkai/ctgov-query-viz-agent/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/yipjunkai/ctgov-query-viz-agent/badge)](https://scorecard.dev/viewer/?uri=github.com/yipjunkai/ctgov-query-viz-agent)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](#-license)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)

**Ask about clinical trials in plain English; get back a validated chart specification grounded in live [ClinicalTrials.gov](https://clinicaltrials.gov/data-api/api) records.** The model plans. Deterministic code computes. Every number is cited back to a real trial — or the agent refuses.

```sh
curl -s localhost:8000/visualize -H 'content-type: application/json' \
  -d '{"query": "How are melanoma trials distributed across phases?", "condition": "melanoma"}'
```

```jsonc
{
  "status": "ok",
  "visualization": {
    "kind": "chart", "type": "bar_chart", "title": "Trials by Phase in melanoma",
    "encoding": { "x": {"field": "key", "label": "Phase"},
                  "y": {"field": "value", "label": "Trial count"} },
    "data": [
      { "key": "PHASE2", "label": "Phase 2", "value": 1528,
        "citations": [{"nct_id": "NCT06896552", "excerpt": "PHASE2", "field": "phase"}] }
      // ...one datum per phase, each with sample citations
    ]
  },
  "meta": {
    "total_trials_matched": 3736, "trials_unclassified": 632, "sort": "canonical phase order",
    "assumptions": ["632 of 3,736 trials report no phase and are excluded from the breakdown.", ...]
  }
}
```

## ⚡ How it works

The whole system is organized around one principle:

> **The LLM is confined to translating a question into a validated query plan.** It never sees a
> record, never emits a count, never writes a citation. Every number in the output is computed by
> deterministic code from real ClinicalTrials.gov records.

The model *cannot* fabricate a trial count because it never produces one. That turns "don't
hallucinate" from a prompt-engineering hope into a structural property — the model's only output is a
typed plan, and anything off-target fails validation instead of reaching the user as a wrong answer.

```text
NL query (+ optional structured fields)
  │
  ▼  planner    ── OpenAI-compatible tool-calling, Pydantic-validated (rule-based fallback, no key)
QueryPlan (intent-discriminated IR)
  │
  ▼  guardrails ── unmappable / out-of-domain / too-broad → typed refusal
  ▼  executor   ── IR filters → CT.gov v2 query params (verified Essie syntax)
  ▼  client     ── count() pre-flight, then page every match (pageToken @ 1000)
  ▼  aggregate  ── deterministic group / bucket / co-occurrence (pure, Counter-based)
  ▼  vizselect  ── (intent, shape) → visualization type + encoding
  ▼  citations  ── attach + verify exact-value excerpts against the source record
  │
  ▼
{ status: ok | refused | needs_clarification, visualization, meta }
```

The LLM appears once, at the top. Everything after it is pure, testable code. That is the seam the
design is built on: **the backend owns all logic, the LLM is a thin adapter at the boundary, and the
response schema is a fixed contract** a frontend can implement against.

## 🚀 Quick start

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.12+.

```sh
uv sync         # create .venv and install deps
just verify     # the single green gate: ruff + strict pyright + tests (no network)
just run        # start the API on http://127.0.0.1:8000
```

**Runs with zero secrets.** With no API key configured the service uses a deterministic rule-based
planner, so it comes up and answers the structured-field queries out of the box. To enable the LLM
planner (needed for free-text entity extraction and multi-series comparisons), drop a key into
`.env`:

```sh
cp .env.example .env    # then set OPENROUTER_API_KEY (preferred) or OPENAI_API_KEY
```

Then ask it something:

```sh
curl -s localhost:8000/visualize -H 'content-type: application/json' \
  -d '{"query": "trials per year for pembrolizumab since 2015", "drug_name": "pembrolizumab"}' | jq
```

## 🎬 Demo

`just run`, then open **http://127.0.0.1:8000/**. Type a question (or click an example chip) and the
page renders the response — charts via **Vega-Lite**, the co-occurrence network via a **Vega
force-directed** graph — alongside the response metadata and the citation table. It's a pure consumer
of the `/visualize` contract with no rendering logic of its own, which is itself the proof that the
schema is frontend-friendly. (It pulls the Vega libraries from a CDN, so the *page* needs internet;
the API and data path don't.)

## 📚 The `/visualize` contract

`POST /visualize` — `query` is required. `GET /` serves the demo; `GET /health` is a liveness probe.

### Request

`query` is the only required field. Any structured field you supply **deterministically overrides**
the planner — explicit user input never depends on the LLM.

| Field        | Type       | Notes                                                     |
|--------------|------------|-----------------------------------------------------------|
| `query`      | string     | The natural-language question. **Required.**              |
| `drug_name`  | string     | Intervention filter (`query.intr`).                       |
| `condition`  | string     | Condition / disease (`query.cond`).                       |
| `sponsor`    | string     | Lead sponsor name (`query.spons`).                        |
| `phase`      | string[]   | Enum: `NA, EARLY_PHASE1, PHASE1, PHASE2, PHASE3, PHASE4`. |
| `country`    | string     | Location country (`query.locn`).                          |
| `start_year` | integer    | Earliest trial start year.                                |
| `end_year`   | integer    | Latest trial start year.                                  |

### Response

Every response is a discriminated union on `status`:

- **`ok`** → `{ status, visualization, meta }`
- **`refused`** → `{ status, reason, message, detail }` — `reason` ∈ `out_of_domain, unsupported,
  too_broad, no_data, upstream_error, planner_failed`. Refusal is a first-class outcome, not an error.
- **`needs_clarification`** → `{ status, question, detail }` — the question was ambiguous.

The **`visualization`** is itself discriminated on `kind`:

- **`chart`** (`bar_chart`, `time_series`, `grouped_bar`, `choropleth`) —
  `{ kind, type, title, encoding: {x, y, series?}, data: [DataPoint] }`, where
  `DataPoint = { key, label, value, series?, citations: [Citation] }`.
- **`network`** (`network_graph`) —
  `{ kind, type, title, encoding: NetworkEncoding, nodes: [Node], edges: [Edge] }`, where
  `Node = { id, label, kind, value }` and `Edge = { source, target, weight, citations }`.

**`Citation` = `{ nct_id, excerpt, field }`** — `excerpt` is the exact value from `field` that placed
the record in that bucket, and is a verified substring of the source record.

**`meta`** carries `source`, `total_trials_matched`, `trials_aggregated`, `trials_unclassified`,
`filters_applied`, `query_interpretation`, `units`, `sort`, `assumptions`, `advisories`,
`resolved_entities`, and `truncated`. `trials_unclassified` + `assumptions` reconcile the bars
against the trial total; `advisories` flag a technically-correct-but-uninformative chart;
`resolved_entities` reports any canonicalized drug names ([see below](#-drug-entity-resolution)).

Seven full request → response runs live in **[`examples/`](examples/)**; the six deterministic ones
(including `07`, a too-broad distribution answered via the facet fast path) regenerate with
`just examples`. The comparison run (`06`) needs an LLM key, since only the LLM planner splits a
comparison into series.

## ✨ Query & visualization coverage

| Question class | Intent         | Visualization   | Example                                       |
|----------------|----------------|-----------------|-----------------------------------------------|
| Distribution   | `distribution` | `bar_chart`     | "trials by phase / status / sponsor type"     |
| Time trend     | `time_trend`   | `time_series`   | "trials per year since 2015"                  |
| Comparison     | `comparison`   | `grouped_bar`   | "compare phases for Drug A vs Drug B"          |
| Geographic     | `geographic`   | `choropleth`    | "which countries have the most trials"        |
| Relationship   | `network`      | `network_graph` | "network of sponsors ↔ drugs; drug ↔ drug"     |

All five run through one engine — adding a class is a new IR variant + one aggregation + one viz
mapping, with no changes to existing code. The no-key rule planner covers everything except
comparison, which needs the LLM planner to split the arms.

## 🧠 Design notes

Why the load-bearing pieces are shaped the way they are.

**Intent-discriminated IR** (`planner/ir.py`). The plan is a Pydantic discriminated union —
`distribution | time_trend | comparison | geographic | network` — over a shared `Filters` block.
Modeling it this way makes illegal states unrepresentable: a `NetworkPlan` *must* carry an entity
pair, a `DistributionPlan` *must* carry a categorical dimension, and neither can hold the other's
fields (`extra="forbid"`). It's the narrowest possible target for the model, and it's the
anti-hallucination boundary expressed in the type system. (Rejected: a flat plan with all-optional
fields, which makes illegal states representable and pushes the policing into hand-written
validators.)

**Controlled vocabulary sourced from the API itself** (`vocab/`). The enum values the planner may
use for `phase`, `status`, `study_type`, `sponsor_class`, and `intervention_type` are pulled from the
API's own `/stats/field/values` endpoint, snapshotted into `snapshot.json`, and enforced by a drift
test. The model can only choose filter values the system certifies exist. Refresh the snapshot with
`python -m ctgov_agent.tools.refresh_vocab`.

**Client-side aggregation, by necessity.** The API's `/stats/field/values` facets return real
server-side counts but are **global-only** — they reject a query filter with `400`. So any *filtered*
count must be computed from real records: the engine pages every matching study (`pageSize=1000` +
`pageToken`) with a compact field projection and counts in code. A `count()` pre-flight, a too-broad
refusal, and an optional on-disk response cache (which also makes the example runs reproducible) keep
that bounded.

**Facet fast path for too-broad distributions** (`engine/pipeline.py`). A distribution is always over
a small controlled-vocab enum (≤14 values), and while the API can't facet a *filtered* query, it
*can* count one exactly. So when a distribution matches more trials than the too-broad threshold,
instead of refusing we issue one server-side `count()` per enum value (plus one "any value" count for
the exact unclassified figure) — no paging. The result is an **exact** chart with sample-backed
citations: "breast cancer trials by phase" (16k+ trials) becomes a real answer in a handful of tiny
requests instead of a flat refusal (see [`examples/07`](examples/07-distribution-too-broad.json)).
Time trends, geography, and networks still need the actual records, so they refuse when too broad —
the fast path applies exactly where the dimension is a closed vocabulary.

**Two-tool planner with validate-and-retry** (`planner/llm.py`). The model gets exactly two tools —
`emit_query_plan` (parameters = the QueryPlan JSON Schema) and `cannot_answer` — and is told to call
one. Its raw arguments always run through Pydantic `parse_plan`; on failure the validation error is
fed back for a single retry; if it still fails, the request is refused.

**Provider strategy with a no-key floor** (`planner/factory.py`, `planner/rules.py`). OpenRouter is
preferred, the OpenAI key is an automatic fallback (both through one OpenAI-compatible client), and
when *no* key is present a deterministic rule-based planner keeps the service running from the
structured request fields. The fallback does no free-text entity extraction and can't split
comparisons, so it refuses those rather than guessing.

**Uniform data points** (`api/schemas.py`). Every chart datum is `{key, label, value, series?,
citations}` regardless of dimension, with `encoding` carrying the human axis labels. A frontend
implements one renderer, not one per query type. (Rejected: semantic per-query field names like
`{"phase": ..., "trial_count": ...}` — self-describing, but the renderer must then discover field
names dynamically.)

**Deep citations as exact, verifiable values** (`engine/citations.py`). Each datum and edge carries
contributing `nct_id`s and an `excerpt` that is the *exact* field value that placed the record in
that bucket — which makes it a provable substring of the source record. A property test enforces the
invariant that every excerpt occurs in its source record. The excerpts are terse (`"PHASE3"`, a
country name, a trial title for edges) precisely because an unverifiable prose snippet is the
hallucination surface this design exists to remove.

**Count reconciliation is explicit, never silent** (`engine/aggregate.py`). Real records break count
conservation two ways: a trial with no value for the grouped dimension (an observational trial has no
phase) lands in *no* bucket, and a multi-value trial (several phases) lands in *several*. So the bars
need not sum to the trial total. Rather than hide that, every `ok` response reports
`meta.trials_unclassified` and a human-readable `meta.assumptions` note ("632 of 3,736 trials report
no phase and are excluded from the breakdown"). A property test ties the numbers to a conservation
law. The alternative — bars that quietly don't add up — is exactly the silent wrongness this design
is built to prevent.

**Low-signal advisories** (`engine/advisories.py`). A count can be perfectly correct and the chart
still useless — a single bar, one value holding 95% of the total, a comparison arm with two trials in
it. Deterministic checks emit a `meta.advisories` note in those cases (kept separate from
`assumptions`, which is about how the counts add up). It never refuses or alters data; it just tells
the reader when not to over-read the picture.

## 💊 Drug entity resolution

`vocab/entities.py` ships a thin, API-verified brand/code → generic map for common oncology drugs. It
exists because of a subtlety worth naming precisely: CT.gov's `query.intr` search already normalizes
most synonyms — *Pembrolizumab*, *Keytruda*, and *MK-3475* all return the same 2,909 trials — but the
normalization is **imperfect** for some drugs (*Herceptin* returns 1,733 trials, *Trastuzumab* 1,702;
`Trastuzumab OR Herceptin` recovers the full 1,733). And the system otherwise has no *awareness* of
entity identity — it can't tell you what canonical drug you searched, or notice that
"Keytruda vs Pembrolizumab" compares a drug with itself.

So the layer earns its place three ways: it (1) OR-expands a recognized drug to the union of its
names — a small real recall win for the imperfectly-indexed ones, a no-op for the rest — (2) surfaces
the resolution in `meta.resolved_entities` so the user sees what was searched, and (3) flags a
same-drug comparison. Every mapping is verified against the live API. It's a curated slice, not a
real ontology — the seam (`resolve_drug`, at the query-building boundary) is exactly where an
RxNorm / ChEMBL lookup would drop in.

## 🧪 Testing

```sh
just verify    # ruff (format + lint) + pyright --strict + pytest   (no network)
just e2e       # live smoke against ClinicalTrials.gov + the real LLM (needs a key; skips if absent)
```

Confidence comes from layered tests behind one gate, not a coverage number:

- **Property (Hypothesis)** — the citation invariant (*every excerpt ⊂ its source record*) and record
  parser totality (*never raises on any input shape*).
- **Unit** — the pure engine: executor param-building (strings verified against the live API),
  aggregation counting (multi-value membership, per-study dedupe), network edge weights, and IR
  validation (every rejection case).
- **Integration** (`TestClient` + injected fake planner + mocked API) — each intent end-to-end to an
  exact visualization spec, and every refusal path.
- **Negative** — out-of-domain → refused, too-broad → refused *without paging*, malformed LLM output
  → retried then refused, upstream 500 → refused.
- **Live smoke** (`just e2e`, network-gated) — proves the CT.gov field mappings and the real
  tool-calling path still hold; skipped cleanly when no key is set.

Beyond the suite, an offline planner eval harness scores the LLM planner against a gold-labeled
question corpus — measuring how often it mis-plans and whether it *refuses* questions it can't answer
rather than force-fitting them. See [`docs/EVAL.md`](docs/EVAL.md) and [`tools/eval/`](tools/eval).

## 🗺️ Roadmap

- [ ] **Ontology-backed entity resolution** — RxNorm / ChEMBL for the full pharmacopoeia and MeSH for
      conditions, replacing the curated oncology map.
- [ ] **Ingestion store for aggregation** — periodically ingest CT.gov into a columnar store and
      aggregate there, turning O(pages)-per-query into a single indexed scan and lifting the
      remaining too-broad limit (time trends, geography, networks).
- [ ] **Self-consistency planning** — sample N plans and take the majority, to drive the residual
      mis-plan rate down.
- [ ] **Richer, still-verified citations** — character-span provenance and a natural-language excerpt
      that is still span-checked against the source.
- [ ] **More intents** — funnel / sankey for enrollment, survival-style timelines; each additive.
- [ ] **A first-party renderer** — ship the Vega-Lite adapter and a real frontend so the specs are
      seen, not just described.

## 📁 Project structure

```text
src/ctgov_agent/
├── api/         # FastAPI app (thin) + the request/response contract
├── planner/     # QueryPlan IR, LLM planner (+ validate/retry), rule fallback, prompt
├── vocab/       # controlled vocabulary from /stats/field/values (+ snapshot) + drug entities
├── ctgov/       # v2 API client (paging, projection, cache) + defensive record parser
├── engine/      # executor · aggregate · network · vizselect · citations · advisories · pipeline
└── web/         # self-contained demo page (a pure consumer of the contract)
tests/           # unit · integration · property · e2e   (single gate: just verify)
examples/        # golden request → response runs
docs/EVAL.md     # offline planner evaluation (harness in tools/eval/)
```

## 🤖 How this was built

Human-owned design, AI-accelerated execution: every load-bearing decision — the "LLM plans, code
computes" seam, the intent-discriminated IR, client-side aggregation (chosen after probing the live
API), the citation-verification invariant — was made deliberately, then implemented in thin slices
behind the `just verify` gate. The full account — tools used, how correctness was validated, and a
human-vs-AI attribution table — is in **[`docs/AGENT_USAGE.md`](docs/AGENT_USAGE.md)**.

## 📄 License

MIT — see [`LICENSE`](LICENSE).
