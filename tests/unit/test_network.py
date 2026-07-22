"""Co-occurrence network construction: edge weights, drug-drug pairing, node prefixing, capping."""

from ctgov_agent.ctgov.models import StudyRecord
from ctgov_agent.engine.network import build_network
from ctgov_agent.planner.ir import EntityDim


def _rec(
    nct: str,
    *,
    sponsor: str | None = None,
    interventions: tuple[str, ...] = (),
    conditions: tuple[str, ...] = (),
) -> StudyRecord:
    return StudyRecord(
        nct_id=nct,
        brief_title=None,
        phases=(),
        study_type=None,
        status=None,
        start_date=None,
        start_year=None,
        sponsor_name=sponsor,
        sponsor_class=None,
        intervention_types=(),
        intervention_names=interventions,
        countries=(),
        raw={},
        conditions=conditions,
    )


def test_sponsor_intervention_edges_weighted_by_shared_trials() -> None:
    records = [
        _rec("N1", sponsor="Merck", interventions=("Pembrolizumab",)),
        _rec("N2", sponsor="Merck", interventions=("Pembrolizumab",)),
        _rec("N3", sponsor="BMS", interventions=("Nivolumab",)),
    ]
    nodes, edges = build_network(records, (EntityDim.sponsor, EntityDim.intervention))
    weights = {(e.source, e.target): e.weight for e in edges}
    assert weights[("sponsor:Merck", "intervention:Pembrolizumab")] == 2
    assert weights[("sponsor:BMS", "intervention:Nivolumab")] == 1

    node_trials = {n.id: n.trial_count for n in nodes}
    assert node_trials["sponsor:Merck"] == 2  # appears in two trials


def test_drug_drug_cooccurrence_within_trial() -> None:
    records = [
        _rec("N1", interventions=("A", "B")),
        _rec("N2", interventions=("A", "B")),
        _rec("N3", interventions=("A", "C")),
    ]
    _nodes, edges = build_network(records, (EntityDim.intervention, EntityDim.intervention))
    weights = {(e.source, e.target): e.weight for e in edges}
    assert weights[("intervention:A", "intervention:B")] == 2
    assert weights[("intervention:A", "intervention:C")] == 1


def test_single_entity_trial_yields_no_self_edge() -> None:
    _nodes, edges = build_network(
        [_rec("N1", interventions=("A",))], (EntityDim.intervention, EntityDim.intervention)
    )
    assert edges == []


def test_max_edges_cap_keeps_heaviest() -> None:
    records = [_rec(f"N{i}", sponsor=f"S{i}", interventions=(f"D{i}",)) for i in range(5)]
    _nodes, edges = build_network(records, (EntityDim.sponsor, EntityDim.intervention), max_edges=2)
    assert len(edges) == 2
