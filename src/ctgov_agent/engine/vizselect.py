"""Choose a visualization type and build its spec from a plan + aggregated buckets.

Viz-type selection is deterministic and driven by the plan's shape, not the LLM's whim: a
distribution over a categorical dimension is a bar chart, ordered by canonical phase order where the
dimension is phase and by descending count otherwise.
"""

from ctgov_agent.api.schemas import Channel, ChartVisualization, DataPoint, Encoding, VizType
from ctgov_agent.engine.aggregate import Bucket
from ctgov_agent.planner.ir import CategoricalDim, DistributionPlan, Filters
from ctgov_agent.vocab.controlled import Phase

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
        data=[DataPoint(key=b.key, label=b.label, value=b.count) for b in ordered],
    )
    return viz, sort_desc
