# Security Policy

## Supported versions

This project is solo-maintained; only the tip of `main` receives fixes. Please
reproduce against the latest `main` before reporting.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Use GitHub's private security advisory mechanism:

1. Go to <https://github.com/yipjunkai/ctgov-query-viz-agent/security/advisories>
2. Click "Report a vulnerability"
3. Fill in the form with as much detail as you can share

Acknowledgement is targeted within 72 hours. The GitHub advisory channel is the
only supported route.

## What to report

- **Prompt-injection / planner-boundary escapes** — a natural-language query (or
  a structured field) that makes the LLM planner emit something outside the
  validated `QueryPlan` IR, smuggle an unintended filter past `extra="forbid"`,
  or otherwise cause the agent to act on attacker-controlled instructions.
- **Robustness / denial-of-service** — a request that bypasses the too-broad
  guard, drives unbounded paging against ClinicalTrials.gov, or triggers a
  crash / unbounded allocation in the record parser or aggregation.
- **Secret exposure** — an API key or other secret surfaced in a response, log
  line, error message, or the on-disk cache.
- **Supply-chain** — a dependency vulnerability not yet flagged by Dependabot or
  `pip-audit`, or an integrity concern in the build.

## What is not in scope

- A wrong or unhelpful visualization / interpretation — that's a correctness bug
  (open a regular bug report), not a vulnerability.
- Unsupported query types — open a feature request.
- Latency or throughput on broad queries — open a regular issue.
