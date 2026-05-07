#!/usr/bin/env python3
"""Optional Evaluator for the OCR Cleaner.

Computes Character Error Rate (CER) on raw OCR text vs ground truth,
and computes CER after ocr_cleaner.clean() to measure improvement.
"""

import argparse
import json
import logging
from pathlib import Path
from difflib import SequenceMatcher

from app.nlp.ocr_cleaner import clean as ocr_clean

logger = logging.getLogger("benchmark_ocr")
logging.basicConfig(level=logging.INFO)

def compute_cer(ref: str, hyp: str) -> float:
    """Compute approximate CER using SequenceMatcher.
    CER = (I + D + S) / N
    SequenceMatcher gives ratio = 2 * M / (T) where T = len(ref) + len(hyp).
    We can approximate CER as 1.0 - ratio if they are reasonably close, 
    or just use sequence matcher operations.
    """
    matcher = SequenceMatcher(None, ref, hyp)
    distance = sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != 'equal')
    return distance / len(ref) if ref else 0.0

def load_dataset(path: str) -> list[dict]:
    with open(path, "r") as f:
        return json.load(f)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="hf_dataset/data/benchmark.json", help="Path to benchmark JSON")
    args = parser.parse_args()

    logger.info(f"Loading OCR benchmark dataset from {args.dataset}...")
    dataset_path = Path(args.dataset)
    dataset = load_dataset(str(dataset_path))
    
    total_cer_before = 0.0
    total_cer_after = 0.0
    count = 0
    
    for case in dataset:
        raw_ocr = case.get("ocr_text", "")
        ground_truth = case.get("clean_text", "")
        
        if not ground_truth:
            continue 
        
        cer_before = compute_cer(ground_truth, raw_ocr)
        
        cleaned = ocr_clean(raw_ocr)
        cer_after = compute_cer(ground_truth, cleaned)
        
        total_cer_before += cer_before
        total_cer_after += cer_after
        count += 1
        
    avg_cer_before = total_cer_before / count if count > 0 else 0
    avg_cer_after = total_cer_after / count if count > 0 else 0
    improvement = (avg_cer_before - avg_cer_after) / avg_cer_before if avg_cer_before > 0 else 0
    
    report = {
        "avg_cer_before": avg_cer_before,
        "avg_cer_after": avg_cer_after,
        "improvement": improvement
    }
    
    with open("benchmark_ocr_report.json", "w") as f:
        json.dump(report, f, indent=2)
        
    logger.info("Evaluation complete. Report written to benchmark_ocr_report.json")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
