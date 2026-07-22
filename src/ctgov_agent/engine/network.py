"""Co-occurrence network construction over parsed study records.

Given two entity types (sponsor / intervention / condition), we build a graph where an edge between
two entities is weighted by the number of trials in which they co-occur. Node ids are type-prefixed
so a sponsor and a drug that happen to share a name never collide. Edges are ranked by weight and
capped (the cap is reported in meta) to keep the graph legible; each edge keeps its member records
so citations can be attached.
"""

from dataclasses import dataclass

from ctgov_agent.ctgov.models import StudyRecord
from ctgov_agent.planner.ir import EntityDim

DEFAULT_MAX_EDGES = 60


@dataclass
class GraphNode:
    id: str
    label: str
    kind: str
    trials: set[str]

    @property
    def trial_count(self) -> int:
        return len(self.trials)


@dataclass
class GraphEdge:
    source: str
    target: str
    members: list[StudyRecord]

    @property
    def weight(self) -> int:
        return len(self.members)


def _entities(record: StudyRecord, dim: EntityDim) -> list[str]:
    if dim is EntityDim.sponsor:
        return [record.sponsor_name] if record.sponsor_name else []
    if dim is EntityDim.intervention:
        return list(record.intervention_names)
    return list(record.conditions)  # EntityDim.condition


def _node_id(dim: EntityDim, name: str) -> str:
    return f"{dim.value}:{name}"


def build_network(
    records: list[StudyRecord],
    endpoints: tuple[EntityDim, EntityDim],
    *,
    max_edges: int = DEFAULT_MAX_EDGES,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    src_dim, dst_dim = endpoints
    nodes: dict[str, GraphNode] = {}
    edge_members: dict[tuple[str, str], list[StudyRecord]] = {}

    def _touch(dim: EntityDim, name: str, record: StudyRecord) -> str:
        node_id = _node_id(dim, name)
        node = nodes.get(node_id)
        if node is None:
            node = GraphNode(id=node_id, label=name, kind=dim.value, trials=set())
            nodes[node_id] = node
        node.trials.add(record.nct_id)
        return node_id

    for record in records:
        pairs: list[tuple[str, str]] = []
        if src_dim == dst_dim:
            names = list(dict.fromkeys(_entities(record, src_dim)))
            ids = [_touch(src_dim, name, record) for name in names]
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    lo, hi = sorted((ids[i], ids[j]))  # undirected, canonical order
                    pairs.append((lo, hi))
        else:
            src_ids = [
                _touch(src_dim, name, record) for name in dict.fromkeys(_entities(record, src_dim))
            ]
            dst_ids = [
                _touch(dst_dim, name, record) for name in dict.fromkeys(_entities(record, dst_dim))
            ]
            pairs = [(s, d) for s in src_ids for d in dst_ids]
        for pair in dict.fromkeys(pairs):  # a trial contributes once per distinct pair
            edge_members.setdefault(pair, []).append(record)

    ranked = sorted(edge_members.items(), key=lambda kv: len(kv[1]), reverse=True)[:max_edges]
    edges = [GraphEdge(source=src, target=dst, members=members) for (src, dst), members in ranked]

    kept_ids = {e.source for e in edges} | {e.target for e in edges}
    kept_nodes = [nodes[node_id] for node_id in kept_ids]
    return kept_nodes, edges
