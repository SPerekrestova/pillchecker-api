import asyncio
import json
import logging
from pathlib import Path

# Adjust path to import from app
import sys
sys.path.append(".")

from app.clients import rxnorm_client, openfda_client
from app.nlp import severity_classifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def enrich_case(case):
    # 1. Clean Text
    # We reconstruct a clean version roughly corresponding to the composition
    case["clean_text"] = f"{case.get('expected_names', [''])[0]} formulation\n{case.get('source_composition', '')}"

    # 2. Expected RxCUIs
    rxcuis = []
    for name in case.get("expected_names", []):
        rxcui = await rxnorm_client.get_rxcui(name)
        if rxcui:
            rxcuis.append(rxcui)
        else:
            # Fallback to approximate if exact fails for ground truth
            cands = await rxnorm_client.approximate_term(name)
            if cands and cands[0].score > 10.0:
                if cands[0].rxcui:
                    rxcuis.append(cands[0].rxcui)
    
    case["expected_rxcuis"] = list(set(rxcuis))
    return case

async def enrich_interactions(multi_cases):
    """Check OpenFDA for real interactions for our sampled multi-ingredient cases to build ground truth."""
    logger.info(f"Checking interactions for {len(multi_cases)} multi-ingredient cases...")
    for case in multi_cases:
        names = case.get("expected_names", [])
        interactions = []
        for i, drug_a in enumerate(names):
            for drug_b in names[i+1:]:
                res = await openfda_client.check_pair(drug_a, drug_b)
                if res is None:
                    res = await openfda_client.check_pair(drug_b, drug_a)
                
                if res:
                    severity, _ = severity_classifier.classify(res["description"])
                    interactions.append({
                        "pair": [drug_a, drug_b],
                        "severity": severity,
                        "description": res["description"]
                    })
        
        case["expected_interactions"] = interactions
    return multi_cases

async def main():
    dataset_path = Path("hf_dataset/data/benchmark.json")
    with open(dataset_path, "r") as f:
        data = json.load(f)

    logger.info(f"Loaded {len(data)} cases.")
    
    enriched = []
    multi_cases = []
    for case in data:
        # We only need 200 multi-ingredient cases
        if case["category"] == "multi_ingredient" or case["category"] == "dual_ingredient":
            if len(multi_cases) < 200:
                multi_cases.append(case)
        
    logger.info("Enriching RxCUIs and Clean Text for all cases...")
    for i, case in enumerate(data):
        enriched_case = await enrich_case(case)
        enriched.append(enriched_case)
        if i % 50 == 0:
            logger.info(f"Processed {i}/{len(data)}")

    await enrich_interactions(multi_cases)

    # Save back to benchmark.json
    with open(dataset_path, "w") as f:
        json.dump(enriched, f, indent=2)
    logger.info(f"Saved enriched dataset to {dataset_path}")

if __name__ == "__main__":
    asyncio.run(main())
