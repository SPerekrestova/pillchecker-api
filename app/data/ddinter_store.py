"""Drug-drug interaction store.

Currently seeded with high-priority DDI pairs from clinical literature.
The interface is designed to be swappable — replace _load_interactions()
with a DDInter scraper, DrugBank CSV parser, or any other source.

Keyed by frozenset of lowercase drug names for bidirectional lookup.
"""

from dataclasses import dataclass

_store: dict[frozenset[str], "Interaction"] = {}


@dataclass
class Interaction:
    drug_a: str
    drug_b: str
    severity: str  # "major", "moderate", "minor"
    description: str
    management: str


def _key(a: str, b: str) -> frozenset[str]:
    return frozenset([a.lower(), b.lower()])


def _load_seed_data() -> dict[frozenset[str], Interaction]:
    """High-priority DDI pairs from clinical sources.

    This seed dataset covers the most dangerous/common interactions.
    Replace with bulk data source (DrugBank, DDInter scrape, etc.) for production.
    """
    pairs = [
        Interaction(
            drug_a="warfarin", drug_b="ibuprofen", severity="major",
            description="NSAIDs may increase the anticoagulant effect of warfarin and increase the risk of bleeding.",
            management="Avoid concurrent use if possible. If necessary, monitor INR closely and watch for signs of bleeding.",
        ),
        Interaction(
            drug_a="warfarin", drug_b="aspirin", severity="major",
            description="Aspirin increases the risk of bleeding when used with warfarin through antiplatelet effects and GI mucosal damage.",
            management="Avoid combination unless specifically indicated (e.g., mechanical heart valve). Monitor for bleeding.",
        ),
        Interaction(
            drug_a="methotrexate", drug_b="ibuprofen", severity="major",
            description="NSAIDs reduce renal clearance of methotrexate, potentially causing toxic accumulation.",
            management="Avoid NSAIDs with high-dose methotrexate. With low-dose, use with caution and monitor renal function.",
        ),
        Interaction(
            drug_a="simvastatin", drug_b="clarithromycin", severity="major",
            description="Clarithromycin inhibits CYP3A4, dramatically increasing simvastatin levels and risk of rhabdomyolysis.",
            management="Contraindicated. Suspend simvastatin during clarithromycin therapy or use an alternative antibiotic.",
        ),
        Interaction(
            drug_a="metformin", drug_b="alcohol", severity="major",
            description="Alcohol potentiates the effect of metformin on lactate metabolism, increasing risk of lactic acidosis.",
            management="Limit alcohol consumption. Avoid binge drinking. Seek medical attention for symptoms of lactic acidosis.",
        ),
        Interaction(
            drug_a="lisinopril", drug_b="potassium", severity="major",
            description="ACE inhibitors reduce potassium excretion. Supplemental potassium may cause dangerous hyperkalemia.",
            management="Avoid potassium supplements unless prescribed. Monitor serum potassium regularly.",
        ),
        Interaction(
            drug_a="fluoxetine", drug_b="tramadol", severity="major",
            description="Both increase serotonin. Combination raises risk of serotonin syndrome (agitation, tremor, hyperthermia).",
            management="Avoid combination. If necessary, use lowest doses and monitor for serotonin syndrome symptoms.",
        ),
        Interaction(
            drug_a="ciprofloxacin", drug_b="tizanidine", severity="major",
            description="Ciprofloxacin inhibits CYP1A2, increasing tizanidine levels up to 10-fold causing severe hypotension and sedation.",
            management="Contraindicated. Use an alternative antibiotic or muscle relaxant.",
        ),
        Interaction(
            drug_a="warfarin", drug_b="acetaminophen", severity="moderate",
            description="Regular acetaminophen use (>2g/day for >3 days) may increase INR and bleeding risk with warfarin.",
            management="Occasional use is generally safe. Monitor INR if using >2g/day for more than a few days.",
        ),
        Interaction(
            drug_a="amlodipine", drug_b="simvastatin", severity="moderate",
            description="Amlodipine inhibits CYP3A4, increasing simvastatin exposure and risk of myopathy.",
            management="Limit simvastatin to 20mg/day when used with amlodipine.",
        ),
        Interaction(
            drug_a="omeprazole", drug_b="clopidogrel", severity="moderate",
            description="Omeprazole inhibits CYP2C19, reducing conversion of clopidogrel to its active metabolite.",
            management="Use pantoprazole instead (less CYP2C19 inhibition). Separate dosing if omeprazole must be used.",
        ),
        Interaction(
            drug_a="metformin", drug_b="contrast dye", severity="moderate",
            description="Iodinated contrast media may cause acute kidney injury, impairing metformin clearance and risking lactic acidosis.",
            management="Withhold metformin before contrast procedure. Resume 48 hours after if renal function is stable.",
        ),
        Interaction(
            drug_a="lithium", drug_b="ibuprofen", severity="major",
            description="NSAIDs reduce renal lithium clearance, potentially causing lithium toxicity.",
            management="Avoid NSAIDs if possible. If used, reduce lithium dose and monitor levels frequently.",
        ),
        Interaction(
            drug_a="digoxin", drug_b="amiodarone", severity="major",
            description="Amiodarone increases digoxin levels by 70-100% through reduced renal and non-renal clearance.",
            management="Reduce digoxin dose by 50% when starting amiodarone. Monitor digoxin levels closely.",
        ),
        Interaction(
            drug_a="sildenafil", drug_b="nitroglycerin", severity="major",
            description="PDE5 inhibitors potentiate the hypotensive effect of nitrates, risking severe and potentially fatal hypotension.",
            management="Contraindicated. Do not use nitrates within 24 hours of sildenafil (48 hours for tadalafil).",
        ),
        Interaction(
            drug_a="sertraline", drug_b="tramadol", severity="major",
            description="Both increase serotonin. Combination raises risk of serotonin syndrome.",
            management="Avoid combination if possible. Use lowest effective doses and monitor for serotonin syndrome.",
        ),
        Interaction(
            drug_a="phenytoin", drug_b="valproic acid", severity="major",
            description="Valproic acid displaces phenytoin from protein binding and inhibits its metabolism, causing toxicity.",
            management="Monitor free phenytoin levels. Adjust dose based on clinical response and levels.",
        ),
        Interaction(
            drug_a="spironolactone", drug_b="lisinopril", severity="moderate",
            description="Both reduce potassium excretion, increasing risk of hyperkalemia.",
            management="Monitor serum potassium closely, especially in patients with renal impairment.",
        ),
        Interaction(
            drug_a="ibuprofen", drug_b="aspirin", severity="moderate",
            description="Ibuprofen may block aspirin's antiplatelet effect if taken before aspirin, reducing cardioprotection.",
            management="Take aspirin at least 30 minutes before ibuprofen, or use ibuprofen at least 8 hours after aspirin.",
        ),
        Interaction(
            drug_a="amoxicillin", drug_b="methotrexate", severity="moderate",
            description="Amoxicillin may reduce renal tubular secretion of methotrexate, increasing methotrexate levels.",
            management="Monitor for methotrexate toxicity. Consider alternative antibiotics for non-serious infections.",
        ),
    ]
    return {_key(p.drug_a, p.drug_b): p for p in pairs}


def load() -> None:
    """Load interaction data into memory. Call once at app startup."""
    global _store
    _store = _load_seed_data()


def check_interaction(drug_a: str, drug_b: str) -> Interaction | None:
    """Check if two drugs have a known interaction.

    Drug names are case-insensitive. Order doesn't matter.
    Returns the Interaction or None if no interaction is known.
    """
    if not _store:
        raise RuntimeError("DDInter store not loaded — call load() first")
    return _store.get(_key(drug_a, drug_b))


def drug_count() -> int:
    """Number of unique drugs in the store."""
    drugs = set()
    for pair in _store:
        drugs.update(pair)
    return len(drugs)


def interaction_count() -> int:
    """Number of interaction pairs in the store."""
    return len(_store)
