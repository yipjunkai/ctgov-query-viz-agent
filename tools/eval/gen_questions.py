"""Generate a stratified, gold-labeled corpus of realistic clinical-trials questions.

Each item carries the *expected* outcome so an audit can score actual-vs-gold automatically:
  - supported:<intent>      -> expected_intent + key expected_filters
  - adversarial:<kind>      -> expected a typed refusal (too_broad / ambiguous / out_of_domain)
  - unsupported:<capability>-> in-domain but outside the 5-intent IR (the coverage gap)

Deterministic (seeded) so the corpus is reproducible.
"""

import argparse
import json
import random

# --- Domain entity pools (realistic; brand/generic pairs included to probe entity resolution) ---
CONDITIONS = [
    "melanoma",
    "breast cancer",
    "non-small cell lung cancer",
    "NSCLC",
    "prostate cancer",
    "glioblastoma",
    "colorectal cancer",
    "pancreatic cancer",
    "multiple myeloma",
    "leukemia",
    "ALS",
    "amyotrophic lateral sclerosis",
    "Alzheimer's disease",
    "Parkinson's disease",
    "multiple sclerosis",
    "epilepsy",
    "type 2 diabetes",
    "obesity",
    "heart failure",
    "atrial fibrillation",
    "hypertension",
    "COPD",
    "asthma",
    "cystic fibrosis",
    "Crohn's disease",
    "ulcerative colitis",
    "rheumatoid arthritis",
    "psoriasis",
    "lupus",
    "COVID-19",
    "HIV",
    "hepatitis B",
    "sickle cell disease",
    "chronic kidney disease",
    "depression",
    "schizophrenia",
    "endometriosis",
    "migraine",
]
DRUGS = [
    "Pembrolizumab",
    "Keytruda",
    "Nivolumab",
    "Opdivo",
    "Ipilimumab",
    "Yervoy",
    "Atezolizumab",
    "Tecentriq",
    "Durvalumab",
    "Trastuzumab",
    "Herceptin",
    "Rituximab",
    "Bevacizumab",
    "Avastin",
    "Osimertinib",
    "Tagrisso",
    "Lenalidomide",
    "Revlimid",
    "Semaglutide",
    "Ozempic",
    "Metformin",
    "Adalimumab",
    "Humira",
    "Dupilumab",
    "Sotorasib",
    "Enfortumab vedotin",
    "Sacituzumab govitecan",
    "CAR-T",
    "tisagenlecleucel",
    "Remdesivir",
    "Paxlovid",
    "Dexamethasone",
    "Aducanumab",
    "Lecanemab",
]
SPONSORS = [
    "Pfizer",
    "Merck",
    "Bristol-Myers Squibb",
    "Roche",
    "Genentech",
    "Novartis",
    "AstraZeneca",
    "Johnson & Johnson",
    "Eli Lilly",
    "Gilead Sciences",
    "Amgen",
    "Moderna",
    "GlaxoSmithKline",
    "Sanofi",
    "Bayer",
    "National Cancer Institute",
    "National Institutes of Health",
]
COUNTRIES = [
    "United States",
    "China",
    "France",
    "Germany",
    "Japan",
    "United Kingdom",
    "Canada",
    "Spain",
    "Italy",
    "South Korea",
    "Australia",
    "India",
    "Brazil",
    "Netherlands",
    "Belgium",
]
STATUSES = ["recruiting", "active", "completed", "terminated", "withdrawn", "not yet recruiting"]
YEARS = list(range(2010, 2025))

R = random.Random(20240722)


def _c() -> str:
    return R.choice(CONDITIONS)


def _d() -> str:
    return R.choice(DRUGS)


def _s() -> str:
    return R.choice(SPONSORS)


def _k() -> str:
    return R.choice(COUNTRIES)


def _y() -> int:
    return R.choice(YEARS)


# --- Supported-intent templates: (question, expected_intent, expected_filters) ---


def t_distribution() -> tuple[str, str, dict]:
    c = _c()
    variants = [
        (
            f"How are {c} trials distributed across phases?",
            "distribution",
            {"condition": c, "dimension": "phase"},
        ),
        (
            f"What's the phase breakdown of {c} trials?",
            "distribution",
            {"condition": c, "dimension": "phase"},
        ),
        (
            f"Show the status distribution of {c} trials.",
            "distribution",
            {"condition": c, "dimension": "status"},
        ),
        (
            f"What are the most common intervention types for {c} trials?",
            "distribution",
            {"condition": c, "dimension": "intervention_type"},
        ),
        (
            f"Break down {c} trials by sponsor type.",
            "distribution",
            {"condition": c, "dimension": "sponsor_class"},
        ),
        (f"phase distribution for {_d()} trials", "distribution", {"dimension": "phase"}),
        (
            f"How many interventional vs observational studies are there for {c}?",
            "distribution",
            {"condition": c, "dimension": "study_type"},
        ),
    ]
    return R.choice(variants)


def t_time_trend() -> tuple[str, str, dict]:
    d, c, y = _d(), _c(), _y()
    variants = [
        (
            f"How has the number of {d} trials changed per year since {y}?",
            "time_trend",
            {"intervention": d, "start_year_min": y},
        ),
        (f"How many {c} trials started each year?", "time_trend", {"condition": c}),
        (f"Show the trend of {c} trials over time.", "time_trend", {"condition": c}),
        (
            f"Trials per year for {d} since {y}",
            "time_trend",
            {"intervention": d, "start_year_min": y},
        ),
        (f"Has {c} research grown over the last decade?", "time_trend", {"condition": c}),
    ]
    return R.choice(variants)


def t_comparison() -> tuple[str, str, dict]:
    d1, d2 = R.sample(DRUGS, 2)
    c1, c2 = R.sample(CONDITIONS, 2)
    variants = [
        (
            f"Compare the phases of {d1} vs {d2} trials.",
            "comparison",
            {"series": [d1, d2], "dimension": "phase"},
        ),
        (
            f"{d1} versus {d2}: how do their trial phases compare?",
            "comparison",
            {"series": [d1, d2], "dimension": "phase"},
        ),
        (
            f"Compare trial status between {d1} and {d2}.",
            "comparison",
            {"series": [d1, d2], "dimension": "status"},
        ),
        (
            f"Compare sponsor categories for {c1} vs {c2} trials.",
            "comparison",
            {"series": [c1, c2], "dimension": "sponsor_class"},
        ),
    ]
    return R.choice(variants)


def t_geographic() -> tuple[str, str, dict]:
    c = _c()
    variants = [
        (f"Which countries have the most {c} trials?", "geographic", {"condition": c}),
        (
            f"Where are recruiting {c} trials happening?",
            "geographic",
            {"condition": c, "status": "recruiting"},
        ),
        (f"Map {c} trials by country.", "geographic", {"condition": c}),
        (f"Which countries run the most {_d()} trials?", "geographic", {}),
    ]
    return R.choice(variants)


def t_network() -> tuple[str, str, dict]:
    c = _c()
    variants = [
        (
            f"Show a network of sponsors and drugs for {c} trials.",
            "network",
            {"condition": c, "endpoints": ["sponsor", "intervention"]},
        ),
        (
            f"Which drugs frequently co-occur in {c} combination studies?",
            "network",
            {"condition": c, "endpoints": ["intervention", "intervention"]},
        ),
        (
            f"Graph the sponsor-drug relationships in {c} research.",
            "network",
            {"condition": c, "endpoints": ["sponsor", "intervention"]},
        ),
        (
            f"What conditions are studied together with {_d()}?",
            "network",
            {"endpoints": ["condition", "intervention"]},
        ),
    ]
    return R.choice(variants)


# --- Adversarial: should produce a typed refusal / clarification ---


def t_too_broad() -> tuple[str, str, dict]:
    variants = [
        "Show the phase distribution of all clinical trials.",
        "How are all trials distributed across phases?",
        "Break down every clinical trial by status.",
        "What's the global distribution of trial phases?",
        "Map all clinical trials by country.",
    ]
    return R.choice(variants), "REFUSE:too_broad", {}


def t_ambiguous() -> tuple[str, str, dict]:
    variants = [
        "trials for it",
        "compare them",
        "show me the graph",
        "what about the other one?",
        "how many are there?",
        "the usual breakdown please",
        "trials",
    ]
    return R.choice(variants), "REFUSE:ambiguous", {}


def t_out_of_domain() -> tuple[str, str, dict]:
    variants = [
        "What's the best pizza in New York?",
        "What's the weather in Boston today?",
        "Who won the World Cup in 2022?",
        "Should I take ibuprofen for my headache?",
        "Write me a poem about spring.",
        "What's the stock price of Pfizer?",
        "Translate 'hello' to French.",
    ]
    return R.choice(variants), "REFUSE:out_of_domain", {}


# --- Unsupported capabilities: in-domain, but outside the 5-intent, count-only IR ---


def t_results() -> tuple[str, str, dict]:
    c, d = _c(), _d()
    variants = [
        f"What was the overall survival rate for {d} in {c} trials?",
        f"Did {d} improve outcomes in {c}?",
        f"What were the primary endpoint results for {d}?",
        f"Which {c} trials met their primary endpoint?",
        f"What's the average response rate across {c} immunotherapy trials?",
    ]
    return R.choice(variants), "UNSUPPORTED:results", {}


def t_enrollment() -> tuple[str, str, dict]:
    c = _c()
    variants = [
        f"What's the average enrollment size for {c} trials?",
        f"How many patients are enrolled in {c} phase 3 trials?",
        f"Which {c} trials have the largest enrollment?",
        f"Total number of participants across {c} trials?",
    ]
    return R.choice(variants), "UNSUPPORTED:enrollment", {}


def t_eligibility() -> tuple[str, str, dict]:
    c, d = _c(), _d()
    variants = [
        f"What are the inclusion criteria for {c} trials?",
        f"What's the typical age range for {c} trial participants?",
        f"Which {d} trials accept patients with prior treatment?",
        f"What are the exclusion criteria for {c} immunotherapy studies?",
    ]
    return R.choice(variants), "UNSUPPORTED:eligibility", {}


def t_safety() -> tuple[str, str, dict]:
    c, d = _c(), _d()
    variants = [
        f"What adverse events were reported for {d}?",
        f"What are the most common side effects in {c} trials?",
        f"How many serious adverse events occurred in {d} trials?",
    ]
    return R.choice(variants), "UNSUPPORTED:safety", {}


def t_trial_lookup() -> tuple[str, str, dict]:
    nct = f"NCT{R.randint(10**7, 10**8 - 1):08d}"
    variants = [
        f"Tell me about trial {nct}.",
        f"What is the status of {nct}?",
        f"Summarize the {_d()} phase 3 trial.",
        f"Who is running {nct}?",
    ]
    return R.choice(variants), "UNSUPPORTED:trial_lookup", {}


def t_investigator() -> tuple[str, str, dict]:
    c = _c()
    variants = [
        f"Which investigators run the most {c} trials?",
        f"Show a network of investigators and sites for {c}.",
        f"Which sites enroll the most patients for {c}?",
    ]
    return R.choice(variants), "UNSUPPORTED:investigator", {}


def t_duration() -> tuple[str, str, dict]:
    c = _c()
    variants = [
        f"How long do phase 3 {c} trials typically take?",
        f"What's the average duration of {c} trials?",
        f"How long from start to completion for {c} studies?",
    ]
    return R.choice(variants), "UNSUPPORTED:duration", {}


# class -> (template_fn, target_count for a 1000-item corpus)
SPEC = {
    "supported:distribution": (t_distribution, 180),
    "supported:time_trend": (t_time_trend, 120),
    "supported:comparison": (t_comparison, 110),
    "supported:geographic": (t_geographic, 110),
    "supported:network": (t_network, 90),
    "adversarial:too_broad": (t_too_broad, 40),
    "adversarial:ambiguous": (t_ambiguous, 40),
    "adversarial:out_of_domain": (t_out_of_domain, 40),
    "unsupported:results": (t_results, 70),
    "unsupported:enrollment": (t_enrollment, 45),
    "unsupported:eligibility": (t_eligibility, 45),
    "unsupported:safety": (t_safety, 40),
    "unsupported:trial_lookup": (t_trial_lookup, 30),
    "unsupported:investigator": (t_investigator, 20),
    "unsupported:duration": (t_duration, 20),
}


def generate(total: int) -> list[dict]:
    scale = total / 1000.0
    items: list[dict] = []
    seen: set[str] = set()
    for klass, (fn, base) in SPEC.items():
        target = max(1, round(base * scale))
        tries = 0
        made = 0
        while made < target and tries < target * 60:
            tries += 1
            q, intent, filt = fn()
            if q in seen:
                continue
            seen.add(q)
            items.append(
                {
                    "id": len(items),
                    "question": q,
                    "klass": klass,
                    "expected_intent": intent,
                    "expected_filters": filt,
                }
            )
            made += 1
    R.shuffle(items)
    for i, it in enumerate(items):
        it["id"] = i
    return items


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--out", default="corpus.jsonl")
    args = ap.parse_args()
    items = generate(args.n)
    with open(args.out, "w") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")
    print(f"wrote {len(items)} questions to {args.out}")


if __name__ == "__main__":
    main()
