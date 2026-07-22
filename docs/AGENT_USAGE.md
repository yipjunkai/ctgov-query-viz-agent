# AI-Assisted Development

An honest account of how this project was built: the tools used, how correctness was validated, and
what was designed deliberately versus generated and adapted. AI tools were used freely for
execution — the engineering judgment behind every load-bearing decision is my own, and this document
maps that ownership to the tests that hold it in place.

## The thesis: human-owned design, AI-accelerated execution

The hard part of a system like this isn't typing the code — it's the judgment. Knowing that an LLM
must **never** be allowed to emit a number. Knowing that the entire aggregation strategy hinges on an
undocumented quirk of the ClinicalTrials.gov API. Knowing that a refusal is a feature, not a failure.
Those calls were made deliberately, up front, before a line of implementation existed. The model was
then a fast, well-directed pair of hands — held to a single green gate (`just verify`) and
human-reviewed before every commit.

The architecture below is a design I chose and can defend, not a shape a model happened to land on:

- **The "LLM plans, code computes" seam.** The model translates a question into a validated
  `QueryPlan` and never sees a record. Every count, bucket, and citation is computed by deterministic
  engine code. This turns "don't hallucinate" from a prompt-engineering *hope* into a structural
  *property* — the model can't fabricate a trial count because it never produces one.
- **The intent-discriminated IR**, modeled so illegal states are unrepresentable — the narrowest
  possible target for the model, chosen over two weaker alternatives I rejected.
- **Client-side aggregation**, chosen only after I probed the live API and discovered
  `/stats/field/values` is global-only (it rejects a query filter with `400`), so any *filtered*
  count must be computed from real records.
- **The citation-verification invariant** — every excerpt is a provable substring of its source
  record.
- **The refusal taxonomy** — `ok / refused / needs_clarification` as first-class, typed outcomes.

## 1. Which tools I used

- **Claude Code (Anthropic)** — implementation under direction. It wrote code to my design in thin
  vertical slices (scaffold → IR → client → one intent → planner → network → citations → guardrails →
  examples → docs), each one gated by `just verify` and reviewed before it was committed.
- **OpenRouter / OpenAI** — the *runtime* planner the service itself calls (an OpenAI-compatible,
  tool-calling model; default `gpt-5-mini`). This is a component of the product, deliberately kept
  distinct from the tooling used to write the code.
- **Standard toolchain** — `uv`, `ruff`, `pyright --strict`, `pytest` + `hypothesis`, all orchestrated
  by a `justfile`.

## 2. How I validated correctness

Not by trusting the model — by pinning every load-bearing claim to something mechanical.

- **One green gate.** `just verify` = `ruff format --check` + `ruff check` + `pyright --strict` +
  `pytest`. Nothing was "done" until it passed; the tree was never left red.
- **Invariants encoded as property tests (Hypothesis).** The anti-hallucination guarantee *is* a
  test: every citation excerpt is a substring of its source record. Count conservation is a test. The
  record parser's totality — *never raises on any input shape* — is a test.
- **API facts were never taken from model memory.** Before writing each layer I probed the live
  ClinicalTrials.gov v2 API and used the actual responses: I confirmed `/stats/field/values` is
  global-only (which decided the whole aggregation strategy), captured the controlled vocabulary into
  a committed snapshot guarded by a drift test, and verified the Essie filter syntax against real
  `200`s before pinning it with tests.
- **Adversarial review.** Code was checked from independent angles — correctness (does the count
  conserve? does the parser stay total?), anti-hallucination (can any excerpt fail to appear in its
  source?), and real-world-data handling (missing fields, multi-value fields, empty results,
  too-broad sets) — each concern turned into a test so it stays checked, not checked once.
- **An offline planner eval with a measured before/after** ([`docs/EVAL.md`](EVAL.md)). An
  899-question, gold-labeled corpus scores the one thing unit tests can't: whether the planner maps
  messy real-world questions to the right plan, and — the acid test — whether it *refuses* the 270
  questions it cannot answer instead of force-fitting a confident, fully-cited wrong answer. Results:
  **100%** supported-intent accuracy with zero mis-plans, and a prompt change I made drove force-fits
  from **6% (16/270) to 0%**, with zero regressions elsewhere. The live tier even surfaced a real
  product gap — high-volume conditions dead-ending as `too_broad` — which I then closed with the
  facet fast path.

## 3. Designed deliberately vs generated and adapted

Everything architectural was designed by me; the model generated implementation against that design,
which I then adapted and reviewed. The table maps each load-bearing decision to who owns it and the
test that holds it in place.

| Area                                     | Designed & owned by            | Verified by                                |
|------------------------------------------|--------------------------------|--------------------------------------------|
| "LLM plans, code computes" thesis        | Me                             | Whole architecture; citation invariant     |
| Intent-discriminated IR shape            | Me (chosen over 2 alternatives)| `test_ir.py` (every rejection case)        |
| Client-side aggregation strategy         | Me (from live API probing)     | API probes + `test_ctgov_client.py`        |
| CT.gov query / filter syntax             | Verified vs the live API       | Probes, then `test_executor.py`, e2e       |
| Vocabulary-from-API guardrail            | Me                             | `test_vocab.py` drift guard                |
| Deep-citation verification invariant     | Me                             | `test_citations_invariant.py` (property)   |
| Refusal taxonomy                         | Me                             | `test_guardrails.py`                        |
| Prompt + tool definitions                | My intent; AI-drafted, I tuned | `test_llm_planner.py` + the eval corpus    |
| Implementation of each vertical slice    | AI-generated to my spec        | Human review + `just verify` on every commit |
| Test suite (the verification itself)     | Me (the test philosophy)       | It *is* the verification                   |

The judgment — knowing exactly where the design holds and where it stops, and probing the API instead
of trusting a plausible guess — is mine, and so is the responsibility for it. The model was leverage
on that judgment, not a substitute for it.
