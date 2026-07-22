"""A thin drug entity-resolution layer: brand names and development codes → a canonical generic.

**Why this exists (and what I learned probing the API).** I assumed brand/generic/code were three
different queries. They mostly are not: CT.gov's ``query.intr`` search already normalizes synonyms,
so *Pembrolizumab*, *Keytruda*, and *MK-3475* all return the same 2,909 trials. But the
normalization is **imperfect** for some drugs — *Herceptin* returns 1,733, *Trastuzumab* only 1,702,
and ``Trastuzumab OR Herceptin`` recovers the full 1,733. So this layer earns its place three ways:
it **canonicalizes** the query to the union of a drug's synonyms (a small but real recall win for
imperfectly-indexed drugs, a no-op for the rest), it **surfaces the resolved entity** in ``meta`` so
the user sees what was searched, and it lets a comparison notice it is comparing a drug **with
itself** (*Keytruda* vs *Pembrolizumab*).

Every mapping below was verified against the live API (brand and generic return the same or a
strict-superset trial set). In production this would be an RxNorm / ChEMBL lookup covering the whole
pharmacopoeia (and conditions via MeSH), not a curated oncology map.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DrugEntity:
    """A drug and its known aliases. ``canonical`` is the INN generic name."""

    canonical: str
    synonyms: tuple[str, ...]

    @property
    def query_term(self) -> str:
        """An Essie ``query.intr`` term matching the union of the drug's names."""
        return " OR ".join((self.canonical, *self.synonyms))


# Curated, API-verified oncology entities. Synonyms are widely documented brand names (plus the one
# development code that anchors the flagship example, MK-3475).
_ENTITIES: tuple[DrugEntity, ...] = (
    DrugEntity("Pembrolizumab", ("Keytruda", "MK-3475")),
    DrugEntity("Nivolumab", ("Opdivo",)),
    DrugEntity("Atezolizumab", ("Tecentriq",)),
    DrugEntity("Durvalumab", ("Imfinzi",)),
    DrugEntity("Trastuzumab", ("Herceptin",)),
    DrugEntity("Bevacizumab", ("Avastin",)),
    DrugEntity("Rituximab", ("Rituxan",)),
    DrugEntity("Imatinib", ("Gleevec",)),
    DrugEntity("Osimertinib", ("Tagrisso",)),
    DrugEntity("Olaparib", ("Lynparza",)),
    DrugEntity("Palbociclib", ("Ibrance",)),
)

# Lowercased alias -> entity, built once. Canonical names are included so an already-generic query
# still resolves (and still reports its aliases).
_LOOKUP: dict[str, DrugEntity] = {
    name.lower(): entity for entity in _ENTITIES for name in (entity.canonical, *entity.synonyms)
}


def resolve_drug(name: str) -> DrugEntity | None:
    """Resolve a drug name (brand, code, or generic) to its canonical entity, if known."""
    return _LOOKUP.get(name.strip().lower())
