import argparse
import asyncio
import json
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any
from huggingface_hub import hf_hub_download

# Import our NLP logic (assuming it's in the same repo now)
try:
    from app.nlp import ner_model
except ImportError:
    import sys
    sys.path.append(".")
    from app.nlp import ner_model

@dataclass
class CaseResult:
    case_id: str
    category: str
    text: str
    expected: list[str]
    ner_found: list[str]
    ner_tp: int
    ner_fp: int
    ner_fn: int
    ner_time_ms: float
    pipeline_found: list[str] = None
    pipeline_tp: int = 0
    pipeline_fp: int = 0
    pipeline_fn: int = 0
    pipeline_time_ms: float = 0.0

def normalize(name: str) -> str:
    return name.lower().strip()

def score(found: list[str], expected: list[str]) -> tuple[int, int, int]:
    f_set = set(normalize(n) for n in found)
    e_set = set(normalize(n) for n in expected)
    tp = len(f_set & e_set)
    fp = len(f_set - e_set)
    fn = len(e_set - f_set)
    return tp, fp, fn

def calc_metrics(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return p, r, f1

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Limit number of cases")
    parser.add_argument("--results-dir", type=str, default="/results", help="Directory to save results")
    parser.add_argument("--dataset", type=str, default="SPerva/pillchecker-ner-benchmark", help="HF Dataset ID")
    args = parser.parse_args()

    # Create results dir
    res_path = Path(args.results_dir)
    res_path.mkdir(parents=True, exist_ok=True)

    # 1. Download dataset from HF Hub
    print(f"Downloading dataset from {args.dataset}...")
    dataset_file = hf_hub_download(repo_id=args.dataset, filename="data/benchmark.json", repo_type="dataset")
    
    with open(dataset_file, "r") as f:
        dataset = json.load(f)

    if args.limit > 0:
        dataset = dataset[:args.limit]
    print(f"Loaded {len(dataset)} test cases.")

    # 2. Load model
    print("Loading NER model...")
    t0 = time.perf_counter()
    ner_model.load_model()
    load_time = time.perf_counter() - t0
    print(f"Model loaded in {load_time:.1f}s")

    # 3. Run evaluation
    results: list[CaseResult] = []
    for case in dataset:
        ocr_text = case["ocr_text"]
        expected_names = case["expected_names"]
        
        t1 = time.perf_counter()
        # Mocking the NER call for the structure, but we use the real model
        ner_found = [e.text for e in ner_model.extract_ingredients(ocr_text)]
        ner_ms = (time.perf_counter() - t1) * 1000
        
        tp, fp, fn = score(ner_found, expected_names)
        results.append(CaseResult(
            case_id=case["id"],
            category=case.get("category", "pharma"),
            text=ocr_text,
            expected=expected_names,
            ner_found=ner_found,
            ner_tp=tp,
            ner_fp=fp,
            ner_fn=fn,
            ner_time_ms=ner_ms,
        ))

    # 4. Overall Metrics
    total_tp = sum(r.ner_tp for r in results)
    total_fp = sum(r.ner_fp for r in results)
    total_fn = sum(r.ner_fn for r in results)
    p, r_val, f1 = calc_metrics(total_tp, total_fp, total_fn)
    
    print(f"\nOVERALL NER: Precision={p:.1%} Recall={r_val:.1%} F1={f1:.1%}")

    # 5. Save results to bucket mount
    output_file = res_path / f"job_result_{int(time.time())}.json"
    output = {
        "timestamp": time.time(),
        "total_cases": len(results),
        "metrics": {"precision": p, "recall": r_val, "f1": f1},
        "cases": [vars(r) for r in results]
    }
    
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"\nResults written to {output_file}")

if __name__ == "__main__":
    main()
