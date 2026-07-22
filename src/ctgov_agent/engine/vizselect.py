"""Choose a visualization type and build its spec from a plan + aggregated buckets.

Viz-type selection is deterministic and driven by the plan's shape, not the LLM's whim: a
distribution over a categorical dimension is a bar chart, ordered by canonical phase order where the
dimension is phase and by descending count otherwise.
"""

from ctgov_agent.api.schemas import (
    Channel,
    ChartVisualization,
    DataPoint,
    Edge,
    Encoding,
    NetworkEncoding,
    NetworkVisualization,
    Node,
    VizType,
)
from ctgov_agent.engine.aggregate import Bucket
from ctgov_agent.engine.citations import bucket_citations, edge_citations
from ctgov_agent.engine.network import GraphEdge, GraphNode
from ctgov_agent.planner.ir import (
    CategoricalDim,
    ComparisonPlan,
    DistributionPlan,
    Filters,
    NetworkPlan,
)
from ctgov_agent.vocab.controlled import Phase, humanize

_DIM_LABEL: dict[CategoricalDim, str] = {
    CategoricalDim.phase: "Phase",
    CategoricalDim.status: "Status",
    CategoricalDim.study_type: "Study Type",
    CategoricalDim.sponsor_class: "Sponsor Class",
    CategoricalDim.intervention_type: "Intervention Type",
}

_PHASE_ORDER: dict[str, int] = {
    p.value: i
    for i, p in enumerate(
        [Phase.EARLY_PHASE1, Phase.PHASE1, Phase.PHASE2, Phase.PHASE3, Phase.PHASE4, Phase.NA]
    )
}


def _title_suffix(filters: Filters) -> str:
    if filters.intervention:
        return f" for {filters.intervention}"
    if filters.condition:
        return f" in {filters.condition}"
    return ""


def distribution_chart(
    plan: DistributionPlan, buckets: list[Bucket]
) -> tuple[ChartVisualization, str]:
    """Bar chart of trial counts across the categorical dimension. Returns (viz, sort_desc)."""
    dim = plan.dimension
    if dim is CategoricalDim.phase:
        ordered = sorted(buckets, key=lambda b: _PHASE_ORDER.get(b.key, len(_PHASE_ORDER)))
        sort_desc = "canonical phase order"
    else:
        ordered = sorted(buckets, key=lambda b: b.count, reverse=True)
        sort_desc = "value desc"

    dim_label = _DIM_LABEL[dim]
    viz = ChartVisualization(
        type=VizType.bar_chart,
        title=f"Trials by {dim_label}{_title_suffix(plan.filters)}",
        encoding=Encoding(
            x=Channel(field="key", label=dim_label),
            y=Channel(field="value", label="Trial count"),
        ),
        data=[
            DataPoint(
                key=b.key, label=b.label, value=b.count, citations=bucket_citations(b, dim.value)
            )
            for b in ordered
        ],
    )
    return viz, sort_desc


def time_series_chart(filters: Filters, buckets: list[Bucket]) -> tuple[ChartVisualization, str]:
    """Trials-per-year line, with intervening zero-years filled so the axis is continuous."""
    by_year = {int(b.key): b for b in buckets}
    years = sorted(by_year)
    data: list[DataPoint] = []
    for year in range(years[0], years[-1] + 1):
        bucket = by_year.get(year)
        citations = (
            bucket_citations(bucket, "start_date", use_start_date=True)
            if bucket is not None
            else []
        )
        data.append(
            DataPoint(
                key=str(year),
                label=str(year),
                value=bucket.count if bucket is not None else 0,
                citations=citations,
            )
        )
    viz = ChartVisualization(
        type=VizType.time_series,
        title=f"Trials per year{_title_suffix(filters)}",
        encoding=Encoding(
            x=Channel(field="key", label="Start year"),
            y=Channel(field="value", label="Trial count"),
        ),
        data=data,
    )
    return viz, "year asc"


def geographic_chart(filters: Filters, buckets: list[Bucket]) -> tuple[ChartVisualization, str]:
    """Choropleth-ready counts by country, ordered by descending count."""
    ordered = sorted(buckets, key=lambda b: b.count, reverse=True)
    viz = ChartVisualization(
        type=VizType.choropleth,
        title=f"Trials by country{_title_suffix(filters)}",
        encoding=Encoding(
            x=Channel(field="key", label="Country"),
            y=Channel(field="value", label="Trial count"),
        ),
        data=[
            DataPoint(
                key=b.key, label=b.label, value=b.count, citations=bucket_citations(b, "country")
            )
            for b in ordered
        ],
    )
    return viz, "value desc"


def _ordered_keys(dim: CategoricalDim, series_results: list[tuple[str, list[Bucket]]]) -> list[str]:
    totals: dict[str, int] = {}
    for _label, buckets in series_results:
        for bucket in buckets:
            totals[bucket.key] = totals.get(bucket.key, 0) + bucket.count
    if dim is CategoricalDim.phase:
        return sorted(totals, key=lambda k: _PHASE_ORDER.get(k, len(_PHASE_ORDER)))
    return sorted(totals, key=lambda k: totals[k], reverse=True)


def comparison_chart(
    plan: ComparisonPlan, series_results: list[tuple[str, list[Bucket]]]
) -> tuple[ChartVisualization, str]:
    """Grouped bar comparing named series across the plan's categorical dimension."""
    dim_label = _DIM_LABEL[plan.dimension]
    data: list[DataPoint] = []
    for key in _ordered_keys(plan.dimension, series_results):
        for label, buckets in series_results:
            match = next((b for b in buckets if b.key == key), None)
            if match is not None:
                data.append(
                    DataPoint(
                        key=key,
                        label=humanize(key),
                        value=match.count,
                        series=label,
                        citations=bucket_citations(match, plan.dimension.value),
                    )
                )
    viz = ChartVisualization(
        type=VizType.grouped_bar,
        title=f"Trials by {dim_label}: {' vs '.join(label for label, _ in series_results)}",
        encoding=Encoding(
            x=Channel(field="key", label=dim_label),
            y=Channel(field="value", label="Trial count"),
            series=Channel(field="series", label="Series"),
        ),
        data=data,
    )
    return viz, "grouped by series"


def network_graph(
    plan: NetworkPlan, nodes: list[GraphNode], edges: list[GraphEdge]
) -> tuple[NetworkVisualization, str]:
    """Node-link graph; node size = trials the entity appears in, edge weight = shared trials."""
    src, dst = plan.endpoints
    ordered_nodes = sorted(nodes, key=lambda n: (-n.trial_count, n.id))
    viz = NetworkVisualization(
        title=f"{humanize(src.value)}-{humanize(dst.value)} network{_title_suffix(plan.filters)}",
        encoding=NetworkEncoding(),
        nodes=[
            Node(id=n.id, label=n.label, kind=n.kind, value=n.trial_count) for n in ordered_nodes
        ],
        edges=[
            Edge(source=e.source, target=e.target, weight=e.weight, citations=edge_citations(e))
            for e in edges
        ],
    )
    return viz, "edges by weight desc"
