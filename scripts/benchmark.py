#!/usr/bin/env python3
"""Multi-tier pipeline evaluator for PillChecker.

Evaluates NER, Entity Linking, and establishes Oracle Upper Bounds.
Includes FP Error Taxonomy classification and Confidence Threshold sweeping.
"""

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from statistics import median, quantiles

from app.nlp import ner_model
from app.nlp.ocr_cleaner import clean as ocr_clean
from app.services.drug_analyzer import analyze
from app.clients import rxnorm_client

logger = logging.getLogger("benchmark")
logging.basicConfig(level=logging.INFO)

# Regexes for FP Taxonomy
SALT_REGEX = re.compile(r"(sodium|hydrochloride|potassium|calcium)", re.IGNORECASE)
MFG_REGEX = re.compile(r"(ltd\.|inc\.|corp\.|pharma|laboratories)", re.IGNORECASE)
FORM_REGEX = re.compile(r"(tablet|capsule|injection|suspension|gummies)", re.IGNORECASE)

class LatencyTracker:
    def __init__(self):
        self.times = defaultdict(list)
    
    def record(self, component: str, duration_ms: float):
        self.times[component].append(duration_ms)
        
    def get_stats(self, component: str):
        data = self.times.get(component, [])
        if not data:
            return {"count": 0}
        q = quantiles(data, n=100) if len(data) >= 100 else (
            sorted(data)[int(len(data)*0.5)], 
            sorted(data)[int(len(data)*0.95)], 
            sorted(data)[int(len(data)*0.99)] if len(data) >= 100 else sorted(data)[-1]
        )
        # Using simpler calculation if < 100 samples
        s = sorted(data)
        n = len(s)
        p50 = s[int(n * 0.5)]
        p95 = s[int(n * 0.95)] if n > 20 else s[-1]
        p99 = s[int(n * 0.99)] if n > 100 else s[-1]
        
        return {
            "count": n,
            "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2),
            "p99_ms": round(p99, 2)
        }

tracker = LatencyTracker()

# --- Monkey-patch for latency tracking ---
original_ner_predict = ner_model.predict
def timed_ner_predict(text):
    start = time.time()
    res = original_ner_predict(text)
    tracker.record("ner_model.predict", (time.time() - start) * 1000)
    return res
ner_model.predict = timed_ner_predict

original_rxnorm_get = rxnorm_client.get_rxcui
async def timed_rxnorm_get(name):
    start = time.time()
    res = await original_rxnorm_get(name)
    tracker.record("rxnorm_client.get_rxcui", (time.time() - start) * 1000)
    return res
rxnorm_client.get_rxcui = timed_rxnorm_get


def load_dataset(path: str) -> list[dict]:
    with open(path, "r") as f:
        return json.load(f)

async def evaluate_ner(dataset: list[dict]) -> dict:
    logger.info("Evaluating NER...")
    all_fps = []
    
    # For F1 tracking at default 0.85
    tp, fp, fn = 0, 0, 0
    
    # Confidence sweeping
    thresholds = [x / 100.0 for x in range(50, 100, 5)]
    sweep_results = {t: {"tp": 0, "fp": 0, "fn": 0} for t in thresholds}
    
    for case in dataset:
        cleaned_text = ocr_clean(case["ocr_text"])
        entities = ner_model.predict(cleaned_text)
        
        drug_entities = [e for e in entities if e.label.upper() in ("CHEM", "CHEMICAL")]
        
        expected = set(n.lower() for n in case["expected_names"])
        predicted_all = {e.text.strip().lower(): e for e in drug_entities}
        
        # Eval at different thresholds
        for t in thresholds:
            pred_t = {k for k, v in predicted_all.items() if v.score >= t}
            sweep_results[t]["tp"] += len(pred_t & expected)
            sweep_results[t]["fp"] += len(pred_t - expected)
            sweep_results[t]["fn"] += len(expected - pred_t)
        
        # Main Eval (0.85 threshold)
        pred_85 = {k: v for k, v in predicted_all.items() if v.score >= 0.85}
        tp += len(set(pred_85.keys()) & expected)
        fn += len(expected - set(pred_85.keys()))
        
        for p in set(pred_85.keys()) - expected:
            fp += 1
            all_fps.append(pred_85[p])
            
    # FP Taxonomy Analysis
    taxonomy = {"brand_name": 0, "salt": 0, "manufacturer": 0, "dosage_form": 0, "digit": 0, "other": 0}
    for e in all_fps:
        txt = e.text.strip()
        if txt.isdigit():
            taxonomy["digit"] += 1
        elif SALT_REGEX.search(txt):
            taxonomy["salt"] += 1
        elif MFG_REGEX.search(txt):
            taxonomy["manufacturer"] += 1
        elif FORM_REGEX.search(txt):
            taxonomy["dosage_form"] += 1
        else:
            # Check brand name via RxNorm
            cands = await rxnorm_client.search_by_name(txt)
            is_brand = False
            for c in cands:
                # If we get a result, and it's a BN (Brand Name), we classify it as such
                # Simple approximation since we just want taxonomy categories
                if c.tty == "BN" or "brand" in c.name.lower():
                    is_brand = True
                    break
            if is_brand:
                taxonomy["brand_name"] += 1
            else:
                taxonomy["other"] += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    
    # Find best threshold
    best_t = 0.85
    best_f1 = f1
    sweep_metrics = {}
    for t in thresholds:
        st_tp = sweep_results[t]["tp"]
        st_fp = sweep_results[t]["fp"]
        st_fn = sweep_results[t]["fn"]
        st_p = st_tp / (st_tp + st_fp) if (st_tp + st_fp) > 0 else 0.0
        st_r = st_tp / (st_tp + st_fn) if (st_tp + st_fn) > 0 else 0.0
        st_f1 = 2 * st_p * st_r / (st_p + st_r) if (st_p + st_r) > 0 else 0.0
        sweep_metrics[t] = {"precision": st_p, "recall": st_r, "f1": st_f1}
        if st_f1 > best_f1:
            best_f1 = st_f1
            best_t = t

    return {
        "metrics_at_85": {"precision": precision, "recall": recall, "f1": f1},
        "optimal_threshold": best_t,
        "optimal_f1": best_f1,
        "fp_taxonomy": taxonomy,
        "sweep_metrics": sweep_metrics
    }


async def evaluate_linking(dataset: list[dict]) -> dict:
    logger.info("Evaluating Entity Linking (RxNorm)...")
    nil_count = 0
    total_ner_entities = 0
    fallback_trigger_count = 0
    fallback_success_count = 0
    
    for case in dataset:
        cleaned_text = ocr_clean(case["ocr_text"])
        entities = ner_model.predict(cleaned_text)
        drug_entities = [e for e in entities if e.label.upper() in ("CHEM", "CHEMICAL") and e.score >= 0.85]
        
        if not drug_entities:
            fallback_trigger_count += 1
            # Simulation of fallback
            start = time.time()
            res = await analyze(case["ocr_text"])
            tracker.record("analyze_total", (time.time() - start) * 1000)
            if res and res[0].get("source") == "rxnorm_fallback":
                fallback_success_count += 1
        else:
            for e in drug_entities:
                total_ner_entities += 1
                rxcui = await rxnorm_client.get_rxcui(e.text.strip())
                if rxcui is None:
                    nil_count += 1
                    
            start = time.time()
            await analyze(case["ocr_text"])
            tracker.record("analyze_total", (time.time() - start) * 1000)
            
    return {
        "nil_rate": nil_count / total_ner_entities if total_ner_entities > 0 else 0,
        "fallback_trigger_rate": fallback_trigger_count / len(dataset) if dataset else 0,
        "fallback_success_rate": fallback_success_count / fallback_trigger_count if fallback_trigger_count > 0 else 0,
    }


async def evaluate_oracle(dataset: list[dict]) -> dict:
    logger.info("Evaluating Oracle Upper Bounds...")
    # Normal Mode
    normal_correct_rxcuis = 0
    total_expected = sum(len(c.get("expected_rxcuis", [])) for c in dataset)
    
    if total_expected == 0:
        logger.warning("No expected_rxcuis found in dataset. Skipping Oracle evaluation.")
        return {
            "normal_mode_rxcui_recall": 0,
            "oracle_ner_mode_rxcui_recall": 0,
            "downstream_cost_of_ner_errors": 0
        }
        
    for case in dataset:
        res = await analyze(case["ocr_text"])
        pred_rxcuis = {r["rxcui"] for r in res if r["rxcui"]}
        expected = set(case.get("expected_rxcuis", []))
        normal_correct_rxcuis += len(pred_rxcuis & expected)
        
    normal_recall = normal_correct_rxcuis / total_expected if total_expected > 0 else 0
    
    # Oracle Mode
    # Monkey-patch the NER model to perfectly return expected names
    async def run_oracle():
        oracle_correct = 0
        original_pred = ner_model.predict
        for case in dataset:
            # Mock perfect NER
            def mock_predict(text):
                return [ner_model.Entity(text=n, label="CHEM", score=1.0, start=0, end=len(n)) for n in case["expected_names"]]
            ner_model.predict = mock_predict
            
            res = await analyze(case["ocr_text"])
            pred_rxcuis = {r["rxcui"] for r in res if r["rxcui"]}
            expected = set(case.get("expected_rxcuis", []))
            oracle_correct += len(pred_rxcuis & expected)
            
        ner_model.predict = original_pred
        return oracle_correct / total_expected if total_expected > 0 else 0

    oracle_recall = await run_oracle()
    
    return {
        "normal_mode_rxcui_recall": normal_recall,
        "oracle_ner_mode_rxcui_recall": oracle_recall,
        "downstream_cost_of_ner_errors": oracle_recall - normal_recall
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, default="hf_dataset/data/benchmark.json")
    args = parser.parse_args()

    logger.info(f"Loading dataset from {args.dataset}...")
    dataset_path = Path(args.dataset)
    if not dataset_path.is_absolute():
        dataset_path = Path(__file__).parent.parent / dataset_path

    dataset = load_dataset(str(dataset_path))
    
    ner_model.load_model()
    
    ner_results = await evaluate_ner(dataset)
    linking_results = await evaluate_linking(dataset)
    oracle_results = await evaluate_oracle(dataset)
    
    report = {
        "ner": ner_results,
        "linking": linking_results,
        "oracle": oracle_results,
        "latency": {
            "ner_model.predict": tracker.get_stats("ner_model.predict"),
            "rxnorm_client.get_rxcui": tracker.get_stats("rxnorm_client.get_rxcui"),
            "analyze_total": tracker.get_stats("analyze_total"),
        }
    }
    
    with open("benchmark_report.json", "w") as f:
        json.dump(report, f, indent=2)
        
    logger.info("Evaluation complete. Report written to benchmark_report.json")

if __name__ == "__main__":
    asyncio.run(main())
