#!/usr/bin/env python3
"""Evaluator for the Interaction Checker and Severity parsers.

Evaluates:
- severity_parser.parse_severity() vs ground truth
- severity_classifier.classify() vs ground truth
- interaction_checker.check() detection recall and false alarm rate
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path

from app.nlp import severity_parser, severity_classifier
from app.services import interaction_checker

logger = logging.getLogger("benchmark_interactions")
logging.basicConfig(level=logging.INFO)

def load_dataset(path: str) -> list[dict]:
    with open(path, "r") as f:
        return json.load(f)

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="hf_dataset/data/benchmark.json", help="Path to benchmark JSON")
    args = parser.parse_args()

    logger.info(f"Loading interaction benchmark dataset from {args.dataset}...")
    dataset_path = Path(args.dataset)
    dataset = load_dataset(str(dataset_path))
    
    multi_cases = [c for c in dataset if c["category"] in ["multi_ingredient", "dual_ingredient"]]
    
    # Severity classification evaluation
    parser_correct = 0
    parser_unknown = 0
    classifier_correct = 0
    total_interactions = 0
    
    # Detection recall
    detection_tp = 0
    detection_fn = 0
    # False alarms
    false_alarms = 0
    total_safe_pairs = 0
    
    for case in multi_cases:
        expected_interactions = case.get("expected_interactions", [])
        drug_names = case.get("expected_names", [])
        
        # We know ground truth for what should be an interaction.
        # Run interaction checker
        res = await interaction_checker.check(drug_names)
        actual_interactions = res.get("interactions", [])
        
        expected_pairs = {frozenset(ix["pair"]): ix for ix in expected_interactions}
        actual_pairs = {frozenset([ix["drug_a"], ix["drug_b"]]): ix for ix in actual_interactions}
        
        # Check recall and false alarms
        for epair, eix in expected_pairs.items():
            if epair in actual_pairs:
                detection_tp += 1
            else:
                detection_fn += 1
                
        for apair in actual_pairs:
            if apair not in expected_pairs:
                false_alarms += 1
                
        # To calculate false alarm RATE, we need to know how many non-interacting pairs there are.
        # Max pairs = n(n-1)/2
        n = len(drug_names)
        max_pairs = n * (n - 1) // 2
        safe_pairs = max_pairs - len(expected_pairs)
        total_safe_pairs += safe_pairs
        
        # Evaluate severity parsing
        for epair, eix in expected_pairs.items():
            total_interactions += 1
            desc = eix["description"]
            expected_sev = eix["severity"]
            
            p_sev = severity_parser.parse_severity(desc)
            if p_sev == "unknown":
                parser_unknown += 1
            elif p_sev == expected_sev:
                parser_correct += 1
                
            c_sev, _ = severity_classifier.classify(desc)
            if c_sev == expected_sev:
                classifier_correct += 1

    report = {
        "detection_recall": detection_tp / (detection_tp + detection_fn) if (detection_tp + detection_fn) > 0 else 0,
        "false_alarms": false_alarms,
        "false_alarm_rate": false_alarms / total_safe_pairs if total_safe_pairs > 0 else 0,
        "severity_evaluation": {
            "total_samples": total_interactions,
            "parser_accuracy": parser_correct / (total_interactions - parser_unknown) if (total_interactions - parser_unknown) > 0 else 0,
            "parser_fallback_rate": parser_unknown / total_interactions if total_interactions > 0 else 0,
            "classifier_accuracy": classifier_correct / total_interactions if total_interactions > 0 else 0
        }
    }
    
    with open("benchmark_interactions_report.json", "w") as f:
        json.dump(report, f, indent=2)
        
    logger.info("Evaluation complete. Report written to benchmark_interactions_report.json")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
