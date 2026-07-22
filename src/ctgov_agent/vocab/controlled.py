"""Controlled vocabularies for ClinicalTrials.gov filter fields.

Every enum here mirrors a field's *actual* value set as reported by the API's own
``/stats/field/values`` endpoint — captured verbatim in ``snapshot.json`` and refreshable with
``python -m ctgov_agent.tools.refresh_vocab``.

Sourcing the vocabulary from the system itself is the first anti-hallucination guardrail: the
planner may only choose filter values the API certifies exist, and ``test_vocab.py`` fails the
build if these enums ever drift from the snapshot. The raw string values (e.g. ``"PHASE2"``) are
exactly what the API accepts as query filters and returns inside study records — humanization for
display happens separately, in :func:`humanize`.

Retrieved 2026-07-22 from https://clinicaltrials.gov/api/v2/stats/field/values
"""

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

SNAPSHOT_PATH = Path(__file__).parent / "snapshot.json"
STATS_FIELD_VALUES_URL = "https://clinicaltrials.gov/api/v2/stats/field/values"

# The ``fields`` (pieces) whose value sets back the enums below.
SNAPSHOT_FIELDS: tuple[str, ...] = (
    "Phase",
    "OverallStatus",
    "StudyType",
    "LeadSponsorClass",
    "InterventionType",
)


class Phase(StrEnum):
    NA = "NA"
    EARLY_PHASE1 = "EARLY_PHASE1"
    PHASE1 = "PHASE1"
    PHASE2 = "PHASE2"
    PHASE3 = "PHASE3"
    PHASE4 = "PHASE4"


class Status(StrEnum):
    ACTIVE_NOT_RECRUITING = "ACTIVE_NOT_RECRUITING"
    COMPLETED = "COMPLETED"
    ENROLLING_BY_INVITATION = "ENROLLING_BY_INVITATION"
    NOT_YET_RECRUITING = "NOT_YET_RECRUITING"
    RECRUITING = "RECRUITING"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    WITHDRAWN = "WITHDRAWN"
    AVAILABLE = "AVAILABLE"
    NO_LONGER_AVAILABLE = "NO_LONGER_AVAILABLE"
    TEMPORARILY_NOT_AVAILABLE = "TEMPORARILY_NOT_AVAILABLE"
    APPROVED_FOR_MARKETING = "APPROVED_FOR_MARKETING"
    WITHHELD = "WITHHELD"
    UNKNOWN = "UNKNOWN"


class StudyType(StrEnum):
    INTERVENTIONAL = "INTERVENTIONAL"
    OBSERVATIONAL = "OBSERVATIONAL"
    EXPANDED_ACCESS = "EXPANDED_ACCESS"


class SponsorClass(StrEnum):
    NIH = "NIH"
    FED = "FED"
    OTHER_GOV = "OTHER_GOV"
    INDIV = "INDIV"
    INDUSTRY = "INDUSTRY"
    NETWORK = "NETWORK"
    AMBIG = "AMBIG"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class InterventionType(StrEnum):
    DRUG = "DRUG"
    BIOLOGICAL = "BIOLOGICAL"
    DEVICE = "DEVICE"
    PROCEDURE = "PROCEDURE"
    BEHAVIORAL = "BEHAVIORAL"
    DIETARY_SUPPLEMENT = "DIETARY_SUPPLEMENT"
    GENETIC = "GENETIC"
    RADIATION = "RADIATION"
    DIAGNOSTIC_TEST = "DIAGNOSTIC_TEST"
    COMBINATION_PRODUCT = "COMBINATION_PRODUCT"
    OTHER = "OTHER"


# Maps each enum to the /stats/field/values "piece" it mirrors — used by the drift guard.
SNAPSHOT_PIECE: dict[type[StrEnum], str] = {
    Phase: "Phase",
    Status: "OverallStatus",
    StudyType: "StudyType",
    SponsorClass: "LeadSponsorClass",
    InterventionType: "InterventionType",
}

# Canonical JSON paths (dot-notation) into a study record. Single source of truth for the client's
# field projection (slice: ctgov client) and the record parser (ctgov/models.py).
FIELD_PATHS: dict[str, str] = {
    "nct_id": "protocolSection.identificationModule.nctId",
    "brief_title": "protocolSection.identificationModule.briefTitle",
    "phase": "protocolSection.designModule.phases",
    "study_type": "protocolSection.designModule.studyType",
    "status": "protocolSection.statusModule.overallStatus",
    "start_date": "protocolSection.statusModule.startDateStruct.date",
    "sponsor_name": "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
    "sponsor_class": "protocolSection.sponsorCollaboratorsModule.leadSponsor.class",
    "intervention_type": "protocolSection.armsInterventionsModule.interventions.type",
    "intervention_name": "protocolSection.armsInterventionsModule.interventions.name",
    "country": "protocolSection.contactsLocationsModule.locations.country",
}

# Tokens whose default title-casing reads wrong; everything else is handled generically.
_LABEL_OVERRIDES: dict[str, str] = {
    "NA": "Not Applicable",
    "EARLY_PHASE1": "Early Phase 1",
    "PHASE1": "Phase 1",
    "PHASE2": "Phase 2",
    "PHASE3": "Phase 3",
    "PHASE4": "Phase 4",
    "NIH": "NIH",
    "FED": "Federal",
    "OTHER_GOV": "Other Government",
    "INDIV": "Individual",
    "AMBIG": "Ambiguous",
}


def humanize(value: str) -> str:
    """Human-readable label for a raw API token, for visualization titles and axes."""
    if value in _LABEL_OVERRIDES:
        return _LABEL_OVERRIDES[value]
    return value.replace("_", " ").title()


def load_snapshot() -> list[dict[str, Any]]:
    """Load the committed golden witness of the API's field-value vocabulary."""
    return json.loads(SNAPSHOT_PATH.read_text())
