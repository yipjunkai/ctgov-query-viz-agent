"""Tier 1: audit the REAL LLM planner, plan-only (no CT.gov paging).

For each question we call planner.plan() and record whether it produced a plan (and which
intent/filters) or refused (and why). Scoring is class-aware:
  - supported:*     -> correct = right intent + right structure (dimension/endpoints/series)
  - unsupported:*   -> correct = REFUSE (a plan here is a 'force-fit': confident answer to an
                       unanswerable question — the failure mode the whole design claims to prevent)
  - out_of_domain   -> correct = refuse(out_of_domain)
  - ambiguous       -> correct = refuse (any reason) / clarification
  - too_broad       -> correct = PRODUCE a plan (too-broad is caught downstream by count(), not here)
"""

import asyncio
import json
import random
import sys
import time

from ctgov_agent.config import get_settings
from ctgov_agent.planner.base import PlannerError
from ctgov_agent.planner.factory import build_planner
from ctgov_agent.planner.ir import ComparisonPlan, DistributionPlan, Filters, NetworkPlan

CORPUS, OUT = sys.argv[1], sys.argv[2]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 500
CONCURRENCY = 8
RNG = random.Random(99)


def stratified(rows: list[dict], n: int) -> list[dict]:
    """All unsupported + all adversarial + fill the rest with supported (proportional by intent)."""
    unsup = [r for r in rows if r["klass"].startswith("unsupported")]
    adv = [r for r in rows if r["klass"].startswith("adversarial")]
    sup = [r for r in rows if r["klass"].startswith("supported")]
    keep_sup = max(0, n - len(unsup) - len(adv))
    RNG.shuffle(sup)
    picked = unsup + adv + sup[:keep_sup]
    RNG.shuffle(picked)
    return picked


def extract(plan) -> dict:
    f = plan.base_filters if isinstance(plan, ComparisonPlan) else plan.filters
    d = {
        "intent": plan.intent,
        "condition": f.condition,
        "intervention": f.intervention,
        "status": [s.value for s in f.status] if f.status else None,
        "start_year_min": f.start_year_min,
    }
    if isinstance(plan, (DistributionPlan, ComparisonPlan)):
        d["dimension"] = plan.dimension.value
    if isinstance(plan, ComparisonPlan):
        d["series"] = [s.label for s in plan.series]
    if isinstance(plan, NetworkPlan):
        d["endpoints"] = [e.value for e in plan.endpoints]
    return d


_done = 0


async def run_one(planner, sem, item, total) -> dict:
    global _done
    async with sem:
        t = time.perf_counter()
        result = None
        for attempt in range(2):
            try:
                plan = await planner.plan(item["question"], Filters())
                result = {"outcome": "plan", **extract(plan)}
                break
            except PlannerError as e:
                result = {"outcome": "refuse", "reason": e.reason, "message": e.message}
                break
            except Exception as e:  # transient API/network — retry once
                result = {"outcome": "error", "error": f"{type(e).__name__}: {e}"}
                if attempt == 0:
                    await asyncio.sleep(2.0)
        result["latency"] = round(time.perf_counter() - t, 2)
        _done += 1
        if _done % 50 == 0:
            print(f"  ... {_done}/{total}", file=sys.stderr, flush=True)
        return {**item, "result": result}


async def main() -> None:
    rows = [json.loads(l) for l in open(CORPUS)]
    sample = stratified(rows, N)
    settings = get_settings()
    planner = build_planner(settings)
    model = getattr(settings, "openai_model", "?")
    print(f"planner={type(planner).__name__} model={model} n={len(sample)}", file=sys.stderr)

    sem = asyncio.Semaphore(CONCURRENCY)
    t0 = time.perf_counter()
    results = await asyncio.gather(*(run_one(planner, sem, it, len(sample)) for it in sample))
    wall = time.perf_counter() - t0
    close = getattr(planner, "aclose", None)
    if close:
        await close()

    with open(OUT, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(results)} results to {OUT} in {wall:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
