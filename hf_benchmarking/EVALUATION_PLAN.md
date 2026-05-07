# PillChecker Pipeline Evaluation Plan

**Date**: 2026-04-26
**Author**: Generated from architecture review of pillchecker-benchmarking, pillchecker-ner-benchmark, and pillchecker-staging repos.

---

## Current Pipeline Architecture

```
OCR text → ocr_cleaner → PharmaDetect NER (108M) → drug_analyzer filter/dedupe → RxNorm normalization
                                                                                        ↓
                        iOS app ← API response ← severity_classifier ← DrugBank/OpenFDA interaction lookup
```

### Repos

| Repo | Purpose |
|------|---------|
| [pillchecker-benchmarking](https://hf.co/SPerva/pillchecker-benchmarking) | NER-only evaluation with `benchmark.py` |
| [pillchecker-ner-benchmark](https://hf.co/datasets/SPerva/pillchecker-ner-benchmark) | 11,796 synthesized pack-label texts (MattBastar/Medicine_Details) |
| [pillchecker-staging](https://hf.co/spaces/SPerva/pillchecker-staging) | Full Docker deployment with GLiNER adjudication experiments |

---

## What the Current Evaluation Covers (and Doesn't)

### ✅ What `benchmark.py` does well

- Measures NER P/R/F1 on ingredient name extraction (set-based, case-insensitive)
- Tests at three OCR noise levels (none/light/heavy)
- Breaks results down by category (single/dual/multi ingredient)
- Includes optional full-pipeline measurement with RxNorm

### ❌ Critical gaps

| Gap | Impact | Why It Matters |
|-----|--------|----------------|
| **No FP error taxonomy** | 🔴 Highest | Precision is 47%, but not *why* — brand names vs salts vs manufacturers vs dosage forms. Without this you can't prioritize fixes. |
| **No RxNorm normalization rate** | 🔴 High | Of the 84% recall entities, what % successfully resolve to an RxCUI? An entity the model finds but RxNorm can't map is useless downstream. |
| **No confidence calibration** | 🟡 High | PharmaDetect outputs confidence scores, but confidence vs correctness is never analyzed. A threshold sweep could recover 15-20pp precision without retraining. |
| **No end-to-end interaction eval** | 🟡 Medium | Smoke tests check 4 hardcoded pairs. No systematic measurement of interaction detection accuracy across DrugBank. |
| **No severity classification eval** | 🟡 Medium | The severity_classifier uses zero-shot DeBERTa + regex fallback, but has never been evaluated against ground truth. |
| **No OCR cleaner isolated eval** | 🟢 Lower | Can't tell how much `ocr_cleaner.py` actually helps. Need CER/WER before→after. |
| **No latency budgets** | 🟢 Lower | Full pipeline = ~961ms/case; RxNorm adds ~900ms. No p50/p95 tracking. |
| **GLiNER experiment modes untested** | 🟡 Medium | Staging has 5 experiment modes but no systematic evaluation of any of them. |

---

## Recommended Evaluation Architecture

Replace `benchmark.py` with a **tiered evaluation harness** that measures every stage independently *and* end-to-end.

### Theoretical Grounding

1. **Component-wise evaluation is NOT consistent with system-wise evaluation** ([Zhao et al., 2020](https://arxiv.org/abs/2005.07362), Section 3.2) — a better NER model in isolation can produce worse end-to-end results if downstream stages interact with errors differently.

2. **Exact-match F1 over-penalizes boundary ambiguity** in biomedical NER ([Distilling LLMs for ADE](https://arxiv.org/abs/2307.06439), Section 4.1) — lenient F1 is 7.7pp higher than strict F1 on the same model. With OCR noise shifting boundaries, you need both.

---

### Tier 1: NER Stage Evaluation (replace current benchmark)

**Strict + Lenient F1**: Current set-based matching is already lenient (name-level, case-insensitive). Add strict span-level matching too, so boundary errors can be quantified separately from entity-type errors.

**FP Error Taxonomy**: Classify every false positive into:

| FP Category | Detection Method | Example |
|------------|-----------------|---------|
| Brand name | RxNorm `tty='BN'` lookup | "Augmentin" tagged as CHEM |
| Salt/counter-ion | Regex: `sodium\|hydrochloride\|calcium\|phosphate\|maleate\|potassium` | "Sodium" in "Diclofenac Sodium" |
| Manufacturer | Check against FDA NDC labeler list or heuristic (ends with Ltd/Inc/Corp) | "Cipla" tagged as CHEM |
| Dosage form | Regex: `tablet\|capsule\|syrup\|injection\|cream` | "Tablet" tagged as CHEM |
| Numeric/dosage | `str.isdigit()` or dosage pattern match | "400" tagged as CHEM |

This immediately tells you: if 60% of FPs are brand names → GLiNER adjudication or RxNorm term-type filtering is the fix. If 30% are salts → the salt-aware adjudicator in staging is the fix.

**Confidence-Precision Curve**: For each confidence threshold from 0.5 to 0.99, compute precision and recall. Plot the tradeoff. The `needs_confirmation: entity.score < 0.85` threshold was chosen ad hoc — the calibration curve will give the optimal threshold for the target precision.

---

### Tier 2: Entity Linking Evaluation (new)

Following the [SapBERT protocol](https://arxiv.org/abs/2010.11784):

| Metric | What it measures |
|--------|-----------------|
| **Acc@1** | % of correctly-extracted ingredients that map to the right RxCUI |
| **NIL rate** | % of correct ingredients with no RxNorm match at all |
| **RxNorm coverage** | % of the 11,796 ground-truth ingredients that exist in RxNorm |
| **Fallback trigger rate** | How often NER finds 0 entities, triggering `_rxnorm_fallback` |

Requires adding `expected_rxcuis` to the benchmark dataset (one-time batch mapping from ingredient names → RxCUIs via the RxNorm API).

---

### Tier 3: Interaction Detection Evaluation (new)

**Ground truth**: The DrugBank SQLite DB already has interaction pairs with severity. Sample N drug pairs from the benchmark's resolved ingredients, create `(drug_a, drug_b, expected_interactions, expected_safe)` tuples.

| Metric | What it measures |
|--------|-----------------|
| **Interaction detection recall** | Of known-interacting pairs, what % does `interaction_checker` find? |
| **Interaction false alarm rate** | Of known-safe pairs, what % does it wrongly flag? |
| **Severity accuracy** | When an interaction IS detected, is severity (major/moderate/minor) correct? |
| **Severity fallback rate** | How often does `severity_parser` return "unknown", triggering the zero-shot classifier? |

Stratified sample:
- 200 cases where NER found ≥2 ingredients → check if DrugBank reports interactions
- 50 known-dangerous pairs (expand beyond the 4 hardcoded smoke test pairs)
- 50 known-safe pairs

---

### Tier 4: End-to-End Oracle Analysis (new)

Run the pipeline twice:

1. **Normal mode**: OCR text → full pipeline → interactions
2. **Oracle NER mode**: Feed gold-standard ingredient names directly to `drug_analyzer._enrich_ner_results` → interactions

```
error_propagation_rate = (oracle_score - pipeline_score) / oracle_score
```

This quantifies exactly how much NER mistakes cost downstream. If interaction checker with oracle NER gets 95% accuracy but full pipeline gets 70%, then 25pp of end-to-end error comes from NER.

---

### Tier 5: GLiNER Experiment Evaluation (systematize what's in staging)

The staging Space has 5 experiment modes controlled by `NER_EXPERIMENT_MODE` env var. Evaluate all on the same benchmark:

| Mode | What it does | Expected impact |
|------|-------------|-----------------|
| `""` (baseline) | PharmaDetect only | Current: P=47%, R=84% |
| `gliner_sequential` | PharmaDetect → GLiNER confirms each entity | ↑ Precision, ↓ Recall |
| `gliner_filter` | PharmaDetect + GLiNER span overlap filter | ↑ Precision (reject brand/mfg) |
| `gliner_adjudicated` | Filter + salt-aware adjudication | ↑ Precision (also reject salts) |
| `gliner_union` | PharmaDetect ∪ GLiNER active ingredients | ↑ Recall |
| `gliner_fallback` | GLiNER when PharmaDetect finds nothing | ↑ Recall on edge cases |

---

## Concrete Implementation Changes

### 1. Extend the benchmark dataset

Current columns: `id, category, ocr_text, expected_names, source_composition`

Add:
- `expected_rxcuis`: Map each `expected_name` to its RxCUI via the RxNorm API (batch job)
- `expected_interactions`: For multi-ingredient cases, pre-compute which pairs interact via DrugBank
- `ocr_noise_level`: Generate clean + light + heavy variants as separate rows or configs

### 2. Replace `benchmark.py` with a multi-tier evaluator

Key structural change: instead of one script that computes P/R/F1, build an evaluation harness that:

1. Runs each pipeline stage independently with its own metrics
2. Runs end-to-end and compares against oracle upper bounds
3. Produces a structured JSON report with all tiers
4. Sweeps confidence thresholds automatically
5. Classifies every FP into the error taxonomy

### 3. Add interaction evaluation ground truth

Stratified sample from the benchmark:
- 200 cases where NER found ≥2 ingredients → check if DrugBank reports interactions
- 50 known-dangerous pairs (expand beyond the 4 hardcoded smoke test pairs)
- 50 known-safe pairs

### 4. Instrument the GLiNER experiments

Run all 5 `NER_EXPERIMENT_MODE` variants on the same 500-case subset. Report a comparison table. This replaces ad-hoc experimentation with systematic A/B evaluation.

---

## Quick Wins (Highest ROI for Least Effort)

### 1. Confidence threshold sweep
Add 10 lines to `benchmark.py` to sweep threshold 0.5→0.99 and plot precision@recall. Likely sweet spot at ~0.75 that raises precision from 47% to ~65% while keeping recall >75%. No retraining needed.

### 2. FP error taxonomy
Add RxNorm `tty` lookup for each false positive entity. Categorize into brand/salt/mfg/form. Takes <1 hour and tells you exactly which filter to build.

### 3. RxNorm normalization rate
In `_enrich_ner_results`, entities where `rxcui is None` are already skipped. Log and count these skips. That number IS the linking evaluation.

### 4. Oracle upper bound
Feed `expected_names` directly to `_enrich_ner_results` and run interaction checking. This gives the pipeline ceiling in 30 minutes of work.

---

## References

| Paper | Relevance |
|-------|-----------|
| [OpenMed NER (2508.01630)](https://arxiv.org/abs/2508.01630) | PharmaDetect architecture, 95.83% F1 on BC5CDR-CHEM |
| [SapBERT (2010.11784)](https://arxiv.org/abs/2010.11784) | Acc@1/Acc@5 entity linking evaluation protocol |
| [PHEE (2210.12560)](https://arxiv.org/abs/2210.12560) | Multi-tier span evaluation with EM_F1 vs Token_F1 |
| [Zhao et al. (2005.07362)](https://arxiv.org/abs/2005.07362) | Component-wise vs system-wise evaluation inconsistency |
| [Distilling LLMs for ADE (2307.06439)](https://arxiv.org/abs/2307.06439) | Lenient vs strict F1 in biomedical NER |
| [MALADE (2408.01869)](https://arxiv.org/abs/2408.01869) | GPT-4 ADE extraction pipeline, AUROC 0.90 vs OMOP |
| [xMEN (2310.11275)](https://arxiv.org/abs/2310.11275) | NIL concept for unmappable entity mentions |
| [NoiseBench (2405.07609)](https://arxiv.org/abs/2405.07609) | Real vs simulated label noise comparison |
| [OHRBench (2412.02592)](https://arxiv.org/abs/2412.02592) | OCR noise robustness evaluation for RAG |
| [Clinical NER Benchmark (2410.05046)](https://arxiv.org/abs/2410.05046) | Token-level vs span-level NER metrics |
| [Calibration of Neural Networks (1706.04599)](https://arxiv.org/abs/1706.04599) | Expected Calibration Error (ECE) |
| [GLiNER-biomed (2504.00676)](https://arxiv.org/abs/2504.00676) | Trained on DailyMed drug label data — directly relevant to pack label domain |
