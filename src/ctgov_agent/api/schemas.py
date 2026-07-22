"""The request and response contract — what a frontend engineer implements against.

Two deliberate choices, documented for the reviewer:

* **Uniform data points.** Every chart datum is ``{key, label, value, series?, citations}``,
  whatever the dimension. The renderer reads one shape for a phase bar chart or a per-year time
  series; ``encoding`` carries the human axis labels. (Rejected: semantic per-query field names
  like ``{"phase": ..., "trial_count": ...}`` — self-describing, but the renderer must then
  discover field names dynamically.)
* **Discriminated responses.** ``status`` tags one of ``ok`` / ``refused`` /
  ``needs_clarification``. Refusal is a first-class, typed outcome — the agent says "I can't
  answer that" instead of guessing.
"""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ctgov_agent.vocab.controlled import Phase


class VizType(StrEnum):
    bar_chart = "bar_chart"
    histogram = "histogram"
    time_series = "time_series"
    grouped_bar = "grouped_bar"
    choropleth = "choropleth"
    network_graph = "network_graph"


class Citation(BaseModel):
    """A traceable link from a visualized datum back to a source trial record."""

    nct_id: str
    excerpt: str
    field: str | None = None


class Channel(BaseModel):
    field: str
    label: str | None = None


class Encoding(BaseModel):
    x: Channel | None = None
    y: Channel | None = None
    series: Channel | None = None


class DataPoint(BaseModel):
    key: str
    label: str
    value: int
    series: str | None = None
    citations: list[Citation] = []


class Node(BaseModel):
    id: str
    label: str
    kind: str
    value: int


class Edge(BaseModel):
    source: str
    target: str
    weight: int
    citations: list[Citation] = []


class ChartVisualization(BaseModel):
    kind: Literal["chart"] = "chart"
    type: VizType
    title: str
    encoding: Encoding
    data: list[DataPoint]


class NetworkVisualization(BaseModel):
    kind: Literal["network"] = "network"
    type: Literal[VizType.network_graph] = VizType.network_graph
    title: str
    encoding: Encoding
    nodes: list[Node]
    edges: list[Edge]


Visualization = Annotated[ChartVisualization | NetworkVisualization, Field(discriminator="kind")]


class Meta(BaseModel):
    source: str = "clinicaltrials.gov"
    total_trials_matched: int
    trials_aggregated: int
    filters_applied: dict[str, Any] = {}
    query_interpretation: str | None = None
    units: str = "trials"
    sort: str | None = None
    assumptions: list[str] = []
    truncated: bool = False


class OkResponse(BaseModel):
    status: Literal["ok"] = "ok"
    visualization: Visualization
    meta: Meta


class RefusedResponse(BaseModel):
    status: Literal["refused"] = "refused"
    reason: str  # machine code: out_of_domain | too_broad | no_data | unsupported_intent | ...
    message: str
    detail: dict[str, Any] = {}


class ClarificationResponse(BaseModel):
    status: Literal["needs_clarification"] = "needs_clarification"
    question: str
    detail: dict[str, Any] = {}


AgentResponse = Annotated[
    OkResponse | RefusedResponse | ClarificationResponse, Field(discriminator="status")
]


class VisualizeRequest(BaseModel):
    """Required ``query`` plus optional structured fields. When a structured field is supplied it
    deterministically overrides the planner — explicit user input never depends on the LLM."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    drug_name: str | None = None
    condition: str | None = None
    sponsor: str | None = None
    phase: list[Phase] | None = None
    country: str | None = None
    start_year: int | None = None
    end_year: int | None = None
