# Evaluation: stress-testing the planner

Confidence in this agent comes from the test suite (see the README) *and* from an offline
stress-test that probes the one part the unit tests can't fully pin down: whether the LLM planner
maps realistic, messy, day-to-day questions to the right plan — and, crucially, whether it **refuses
questions it cannot answer instead of forcing a wrong one**.

The harness that produced these numbers lives in [`tools/eval/`](../tools/eval); it is reproducible.

## Method

A grammar generates a **gold-labeled corpus** — each question carries its expected outcome, so
scoring is automatic (actual-vs-gold), not eyeballed. The corpus is stratified across 15 classes:

- **5 supported intents** (distribution, time_trend, comparison, geographic, network) — expect a plan.
- **3 adversarial** (out_of_domain, ambiguous, too_broad) — expect a refusal / clarification /
  deferral. (`too_broad` is special: the planner *should* produce a plan; too-broad is caught
  downstream by the `count()` pre-flight, not the planner.)
- **7 unsupported capabilities** — in-domain questions the count-only IR cannot express (results /
  efficacy, enrollment size, eligibility, safety / adverse events, single-trial lookup, investigators
  / sites, trial duration). These **must be refused**.

It runs in tiers so signal-per-dollar stays high:

| Tier | What | Cost |
|------|------|------|
| **0** | Validate every gold label constructs a legal `QueryPlan`; fuzz the deterministic spine (param-build, viz builders) | free, no LLM, no network |
| **1** | Run the **real LLM planner, plan-only** (no CT.gov paging); diff actual-vs-gold | ~500 model calls |
| **2** | A curated handful full end-to-end against live CT.gov | ~25 requests |

## Results

Run over an 899-question corpus (Tier 1 sampled the 500 highest-signal: all 270 unsupported + all
adversarial + 211 supported).

**Tier 0 — the deterministic spine is not the risk.** All 610 supported gold labels construct valid
IR plans; zero param-build or viz-builder crashes over the corpus. Messy real names (`Crohn's
disease`, `Johnson & Johnson`) pass straight into `query.cond` — never the Essie filter string — so
there's no injection surface there. Conclusion: the entire risk surface is the planner.

**Tier 1 — the planner is accurate on what it supports, and the acid test is refusal.**

| Metric | Result |
|--------|--------|
| Supported intent accuracy (n=211) | **100%** — zero mis-plans |
| Supported structural accuracy (dimension / endpoints / series) | **100%** |
| Adversarial handling (n=19) | **100%** |
| **Unsupported → correctly refused (n=270)** | **see below** |
| Planner latency, plan-only | p50 ~7–10s, p95 ~11–18s |

The acid test is the 270 unsupported questions, where the *correct* answer is `cannot_answer`. A plan
there is a **force-fit**: a confident, fully-cited answer to a question the system cannot actually
answer — the exact failure the architecture exists to prevent. This is also where a prompt change was
measured before/after:

| | Force-fit (bad) | Refused (good) |
|--|--|--|
| **Before** (intents listed, out-of-scope implicit) | 6% (16/270) | 94% |
| **After** (explicit out-of-scope list + refusal few-shots) | **0% (0/270)** | **100%** |

Zero regressions elsewhere: supported intent accuracy stayed 100% (no over-refusal), adversarial
handling stayed 100%. The fix was a systematic one — the leaks clustered on patterns like *"Did
[drug] improve outcomes in [condition]?"* (efficacy) and *"Summarize the [drug] phase 3 trial"*
(single-trial lookup), where entity/keyword triggers overrode the unanswerable verb. Naming the
out-of-scope categories in the prompt closed them. (As a side effect, plan-only p50 latency dropped
~35%: the unsupported half of the sample now short-circuits to a refusal instead of deliberating.)

**Tier 2 — live end-to-end (n=25): 24/25 expected status.** All five intents render against live
data; every refusal path fires correctly end-to-end. The one deviation is a **real product finding,
not a bug**: *"status breakdown of breast cancer trials"* is refused as `too_broad` — breast cancer
matches **16,627** trials (diabetes: 24,134), both above the 10k exact-aggregation threshold. Common,
well-scoped questions about high-volume conditions currently dead-end; the fix is a partial-with-caveat
response or the ingestion store (see the README's "What I'd do next").

## Reproducing

See [`tools/eval/README.md`](../tools/eval/README.md). In short: generate a corpus, run Tier 0 free,
then Tier 1/2 with an LLM key configured.

## What this is not

The corpus proportions are a *design choice* for balanced coverage, not a measured real-world
frequency. And the highest-value open extension is a **chart-fitness judge** — scoring whether the
rendered visualization actually answers the question (an offline LLM-judge over this same corpus),
which would catch the degenerate-but-valid chart (a single dominant bucket, a near-empty comparison
series) that current guards don't.
