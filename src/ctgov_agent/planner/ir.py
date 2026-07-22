"""The QueryPlan intermediate representation — the LLM's *only* output.

Design: the planner translates a question into one of a small, closed set of intent-shaped plans.
It never emits a count, a data value, or a citation; those are computed downstream from real API
records. Modelling the plan as an **intent-discriminated union** makes illegal states
unrepresentable — a ``NetworkPlan`` *must* carry an entity pair, a ``DistributionPlan`` *must*
carry a categorical dimension, and neither can hold the other's fields (``extra="forbid"``). That
is the anti-hallucination boundary expressed in the type system: the model's target is as narrow
as we can make it, and anything off-target fails validation instead of producing a wrong answer.

Adding a query class is additive: a new plan variant + one executor branch + one viz mapping — no
changes to existing variants. That is the "single coherent approach / no one-off hacks" the brief
asks for.
"""

from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from ctgov_agent.vocab.controlled import (
    MAX_YEAR,
    MIN_YEAR,
    InterventionType,
    Phase,
    SponsorClass,
    Status,
    StudyType,
)


class CategoricalDim(StrEnum):
    """A categorical field a distribution/comparison can be broken down by."""

    phase = "phase"
    status = "status"
    study_type = "study_type"
    sponsor_class = "sponsor_class"
    intervention_type = "intervention_type"


class EntityDim(StrEnum):
    """An entity type that can form a node set in a relationship network."""

    sponsor = "sponsor"
    intervention = "intervention"
    condition = "condition"


class Filters(BaseModel):
    """Structured constraints on the trial set. Every field is optional; enum-typed fields are
    constrained to the API's own controlled vocabulary."""

    model_config = ConfigDict(extra="forbid")

    condition: str | None = None
    intervention: str | None = None
    sponsor: str | None = None
    country: str | None = None
    phase: list[Phase] | None = None
    status: list[Status] | None = None
    study_type: list[StudyType] | None = None
    sponsor_class: list[SponsorClass] | None = None
    intervention_type: list[InterventionType] | None = None
    start_year_min: int | None = None
    start_year_max: int | None = None

    @model_validator(mode="after")
    def _validate_years(self) -> Self:
        for year in (self.start_year_min, self.start_year_max):
            if year is not None and not (MIN_YEAR <= year <= MAX_YEAR):
                raise ValueError(f"year {year} outside plausible range [{MIN_YEAR}, {MAX_YEAR}]")
        lo, hi = self.start_year_min, self.start_year_max
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"start_year_min ({lo}) must be <= start_year_max ({hi})")
        return self


class Series(BaseModel):
    """One named arm of a comparison (e.g. "Pembrolizumab") with its own filter set."""

    model_config = ConfigDict(extra="forbid")

    label: str
    filters: Filters


class _Plan(BaseModel):
    """Fields shared by every plan variant."""

    model_config = ConfigDict(extra="forbid")

    notes: str | None = Field(
        default=None,
        description="The planner's interpretation of the question and any assumptions it made.",
    )


class DistributionPlan(_Plan):
    """How trials distribute across the values of one categorical dimension (bar chart)."""

    intent: Literal["distribution"]
    dimension: CategoricalDim
    filters: Filters = Field(default_factory=Filters)


class TimeTrendPlan(_Plan):
    """Trial counts bucketed by start year (time series). Granularity is fixed to year; month is a
    documented extension (see the README's design section)."""

    intent: Literal["time_trend"]
    filters: Filters = Field(default_factory=Filters)


class ComparisonPlan(_Plan):
    """Two or more named series compared across a categorical dimension (grouped bar)."""

    intent: Literal["comparison"]
    dimension: CategoricalDim
    series: list[Series] = Field(min_length=2)
    base_filters: Filters = Field(
        default_factory=Filters,
        description="Filters shared by every series (e.g. a common condition).",
    )


class GeographicPlan(_Plan):
    """Trial counts by country (choropleth/bar). The dimension is implicitly country."""

    intent: Literal["geographic"]
    filters: Filters = Field(default_factory=Filters)


class NetworkPlan(_Plan):
    """Co-occurrence network between two entity types; edge weight = shared-trial count."""

    intent: Literal["network"]
    endpoints: tuple[EntityDim, EntityDim]
    filters: Filters = Field(default_factory=Filters)


QueryPlan = Annotated[
    DistributionPlan | TimeTrendPlan | ComparisonPlan | GeographicPlan | NetworkPlan,
    Field(discriminator="intent"),
]

_ADAPTER: TypeAdapter[QueryPlan] = TypeAdapter(QueryPlan)


def parse_plan(data: dict[str, Any]) -> QueryPlan:
    """Validate a raw dict (from the LLM) into a typed QueryPlan, raising on anything off-target."""
    return _ADAPTER.validate_python(data)


def query_plan_json_schema() -> dict[str, Any]:
    """JSON Schema for the whole union (a top-level ``oneOf``). Used to build the tool schema."""
    return _ADAPTER.json_schema()


def query_plan_tool_schema() -> dict[str, Any]:
    """QueryPlan wrapped as an OpenAI-compatible function-parameters object.

    Function ``parameters`` must be a ``type: object`` schema, but a discriminated union is a
    top-level ``oneOf``. We wrap the union under a ``plan`` property, hoist ``$defs`` to the root so
    ``$ref``s still resolve, and normalize ``oneOf``→``anyOf`` (dropping the ``discriminator``
    keyword, which OpenAI function-calling rejects). Pydantic still discriminates in ``parse_plan``.
    """
    union = query_plan_json_schema()
    defs = union.pop("$defs", {})
    union.pop("discriminator", None)
    if "oneOf" in union:
        union["anyOf"] = union.pop("oneOf")
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"plan": union},
        "required": ["plan"],
        "$defs": defs,
    }
