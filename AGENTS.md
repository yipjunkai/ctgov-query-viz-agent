# AGENTS.md

Guidance for AI coding agents (Claude Code / Cursor) working in this repo.

## Golden rule

**Run `just verify` before you're done, and never leave the tree red.** It is the single gate:
`ruff format --check` + `ruff check` + `pyright --strict` + `pytest`. `just e2e` runs the
network-gated live tests separately.

## Non-negotiables

- **Don't trust model memory for API facts.** ClinicalTrials.gov field names, filter syntax, and
  enum values must come from the live API or the committed `src/ctgov_agent/vocab/snapshot.json`,
  not from recall. Probe first, then encode, then pin with a test.
- **The LLM never emits data.** Keep the seam: the planner produces a validated `QueryPlan` only;
  all counts/buckets/citations are computed by deterministic engine code. Any change that lets the
  model produce a number is wrong.
- **Refuse over guess.** New failure modes become typed `refused` / `needs_clarification` responses
  with a test, not silent wrong answers or 500s.
- **Every citation excerpt must be a substring of its source record** (`test_citations_invariant`).

## Conventions

- Commits: plain imperative, capitalized subject describing the outcome; one concern per commit.
- Adding a query class = new IR variant + one executor branch + one aggregation + one viz mapping +
  tests. Don't special-case.
- Keep `src/` fully strict-typed; test-only third-party typing gaps are relaxed in `[tool.pyright]`.

## Where things live

`api/` HTTP + schemas · `planner/` IR + LLM/rule planners + prompt · `vocab/` controlled vocabulary ·
`ctgov/` API client + parser · `engine/` executor/aggregate/network/vizselect/citations/pipeline.
