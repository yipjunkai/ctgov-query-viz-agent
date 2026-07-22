"""Tier 0 (free, no LLM, no network): validate gold labels + fuzz the deterministic spine.

1. Every 'supported' gold label must construct a *valid* QueryPlan (a legal target exists in the IR).
2. build_query_params must not crash on real, messy entity names (Crohn's, Johnson & Johnson, unicode).
3. The viz builders must not crash across intents over a fixture record set.
"""

import json
import sys
from pathlib import Path

from ctgov_agent.ctgov.models import parse_study
from ctgov_agent.engine.aggregate import (
    aggregate_by_country,
    aggregate_by_dimension,
    aggregate_by_year,
)
from ctgov_agent.engine.executor import build_query_params, combine_filters
from ctgov_agent.engine.network import build_network
from ctgov_agent.engine.vizselect import (
    comparison_chart,
    distribution_chart,
    geographic_chart,
    network_graph,
    time_series_chart,
)
from ctgov_agent.planner.ir import (
    CategoricalDim,
    ComparisonPlan,
    DistributionPlan,
    EntityDim,
    Filters,
    NetworkPlan,
    Series,
    parse_plan,
)

CORPUS = sys.argv[1]
FIXTURE = Path("tests/fixtures/ctgov_search_melanoma.json")

_STATUS_MAP = {
    "recruiting": "RECRUITING",
    "active": "ACTIVE_NOT_RECRUITING",
    "completed": "COMPLETED",
}


def gold_plan(intent: str, f: dict):
    """Build the expected QueryPlan dict from a gold label, then parse it (raises if illegal)."""
    filt = {}
    if f.get("condition"):
        filt["condition"] = f["condition"]
    if f.get("intervention"):
        filt["intervention"] = f["intervention"]
    if f.get("start_year_min"):
        filt["start_year_min"] = f["start_year_min"]
    if f.get("status"):
        filt["status"] = [_STATUS_MAP.get(f["status"], "RECRUITING")]
    if intent == "distribution":
        return parse_plan({"intent": "distribution", "dimension": f["dimension"], "filters": filt})
    if intent == "time_trend":
        return parse_plan({"intent": "time_trend", "filters": filt})
    if intent == "geographic":
        return parse_plan({"intent": "geographic", "filters": filt})
    if intent == "network":
        return parse_plan({"intent": "network", "endpoints": f["endpoints"], "filters": filt})
    if intent == "comparison":
        key = "intervention" if f["dimension"] != "sponsor_class" else "condition"
        # sponsor_class comparisons in the corpus vary by condition; drug comparisons by intervention
        series = [{"label": s, "filters": {key: s}} for s in f["series"]]
        return parse_plan({"intent": "comparison", "dimension": f["dimension"], "series": series})
    raise ValueError(intent)


def main() -> None:
    rows = [json.loads(l) for l in open(CORPUS)]
    supported = [r for r in rows if r["klass"].startswith("supported")]

    gold_ok, gold_fail = 0, []
    param_fail = []
    for r in supported:
        try:
            plan = gold_plan(r["expected_intent"], r["expected_filters"])
            gold_ok += 1
        except Exception as e:
            gold_fail.append((r["question"], f"{type(e).__name__}: {e}"))
            continue
        # param-encoding on the plan's filters (exercises real entity names)
        try:
            if isinstance(plan, ComparisonPlan):
                for s in plan.series:
                    build_query_params(combine_filters(plan.base_filters, s.filters))
            else:
                build_query_params(plan.filters)
        except Exception as e:
            param_fail.append((r["question"], f"{type(e).__name__}: {e}"))

    # viz-builder crash smoke over a real fixture, once per intent
    records = [parse_study(s) for s in json.loads(FIXTURE.read_text())["studies"]]
    viz_fail = []
    try:
        distribution_chart(
            DistributionPlan(
                intent="distribution", dimension=CategoricalDim.phase, filters=Filters()
            ),
            aggregate_by_dimension(records, CategoricalDim.phase),
        )
        time_series_chart(Filters(), aggregate_by_year(records))
        geographic_chart(Filters(), aggregate_by_country(records))
        comparison_chart(
            ComparisonPlan(
                intent="comparison",
                dimension=CategoricalDim.phase,
                series=[Series(label="A", filters=Filters()), Series(label="B", filters=Filters())],
            ),
            [
                ("A", aggregate_by_dimension(records, CategoricalDim.phase)),
                ("B", aggregate_by_dimension(records, CategoricalDim.phase)),
            ],
        )
        n, e = build_network(records, (EntityDim.sponsor, EntityDim.intervention))
        network_graph(
            NetworkPlan(
                intent="network",
                endpoints=(EntityDim.sponsor, EntityDim.intervention),
                filters=Filters(),
            ),
            n,
            e,
        )
    except Exception as ex:
        viz_fail.append(f"{type(ex).__name__}: {ex}")

    print(f"supported items:                 {len(supported)}")
    print(f"gold labels -> valid IR plan:    {gold_ok}/{len(supported)}")
    print(f"param-build failures:            {len(param_fail)}")
    print(f"viz-builder crashes:             {len(viz_fail)}")
    print()
    if gold_fail:
        print("GOLD-LABEL FAILURES (corpus bugs or IR gaps):")
        for q, e in gold_fail[:10]:
            print(f"  - {q}\n      {e}")
    if param_fail:
        print("PARAM-BUILD FAILURES:")
        for q, e in param_fail[:10]:
            print(f"  - {q}  ({e})")
    if viz_fail:
        print("VIZ FAILURES:", viz_fail)
    if not (gold_fail or param_fail or viz_fail):
        print(
            "No crashes in the deterministic spine over the corpus. (Expected: it's property-tested.)"
        )

    # sanity: show params for the messiest entity names actually present
    print("\nparam-encoding spot check on messy names:")
    for name in ["Crohn's disease", "Johnson & Johnson", "non-small cell lung cancer"]:
        print(f"  cond={name!r:34s} -> {build_query_params(Filters(condition=name))}")


if __name__ == "__main__":
    main()
