# NER Benchmark: PharmaDetect on Pill Packaging Text

**Date**: 2026-04-14
**Model**: `OpenMed/OpenMed-NER-PharmaDetect-BioPatient-108M` (108M params)
**Dataset**: 11,796 synthesized pack-label texts from HuggingFace `MattBastar/Medicine_Details`
**Pipeline tested**: OCR cleaner → NER entity extraction (no RxNorm validation)

## Dataset

### Source

[MattBastar/Medicine_Details](https://huggingface.co/datasets/MattBastar/Medicine_Details)
— 11,825 Indian brand medicines with structured Composition, Manufacturer,
Uses, and Image URL fields. We use the Medicine Name + Composition +
Manufacturer columns to synthesize realistic pack-label OCR text.

### How It Works

`prepare_hf_dataset.py` takes each row and:

1. **Synthesizes a pack label** from a random template (blister pack,
   box label, prescription-style, syrup label, etc.):

   ```
   Augmentin 625 Duo Tablet
   Each tablet contains:
   Amoxycillin 500mg
   Clavulanic Acid 125mg
   Glaxo SmithKline Pharmaceuticals Ltd
   ```

2. **Parses ground-truth labels** from the Composition field:
   `"Amoxycillin (500mg) + Clavulanic Acid (125mg)"` → `["Amoxycillin", "Clavulanic Acid"]`

3. **Optionally injects OCR noise** (`--noise light|heavy`) using
   pharma-specific distortion patterns drawn from real OCR failures:

   | Pattern | Example | Source |
   |---------|---------|--------|
   | m→rn | Metformin → Metforrnin | Glyph confusion in serif fonts |
   | I→l (word start) | Ibuprofen → lbuprofen | Uppercase I vs lowercase L |
   | l→1 (interior) | Alprazolam → A1prazolam | l/1 confusion |
   | o→0 / O→0 | Omeprazole → 0mepraz0le | Letter/digit confusion |
   | cl→d | Clavulanic → Davulanic | Ligature misread |
   | mg→rng | 500mg → 500rng | m→rn in dosage suffix |
   | Mid-word splits | Bevacizumab → Bevacizu mab | Line-wrap OCR artifact |
   | All-caps | ATORVASTATIN 40MG | Uppercase printed labels |

### Category Breakdown

| Category | N | Description |
|----------|---|-------------|
| single_ingredient | 7,081 | One active ingredient (e.g., Azithromycin) |
| dual_ingredient | 3,591 | Two active ingredients (e.g., Amoxycillin + Clavulanic Acid) |
| multi_ingredient | 1,124 | Three or more active ingredients |

### Reproducing

```bash
uv run python eval/prepare_hf_dataset.py                  # clean text (default)
uv run python eval/prepare_hf_dataset.py --noise light     # light OCR artifacts
uv run python eval/prepare_hf_dataset.py --noise heavy     # heavy OCR distortion
uv run python eval/prepare_hf_dataset.py --limit 500       # smaller sample
```

## About the Model

### Architecture

PharmaDetect-BioPatient-108M is a token-classification (NER) model from the
[OpenMed NER](https://arxiv.org/abs/2508.01630) suite (Panahi, 2025). It
detects chemical entities using BIO tagging (`B-CHEM`, `I-CHEM`).

| Property | Value |
|----------|-------|
| Base model | [`Bio_Discharge_Summary_BERT`](https://huggingface.co/emilyalsentzer/Bio_Discharge_Summary_BERT) (BioBERT v1.0 → MIMIC-III discharge summaries, ~880M words) |
| DAPT corpus | 350k passages (90M tokens): 100k PubMed, 100k arXiv, 100k MIMIC-III, 50k ClinicalTrials.gov |
| DAPT method | LoRA (rank=16, α=32, dropout=0.05) on query/value matrices, 3 epochs, single A100 ~4h |
| Fine-tuning dataset | BC5CDR-CHEM (BioCreative V Chemical-Disease Relation) |
| Parameters | 108M (1.4% trainable via LoRA during DAPT) |
| Entity types | Chemical entities only (`B-CHEM` / `I-CHEM`) |
| Published F1 | 95.83% on BC5CDR-CHEM test set |

### Domain Gap: Literature vs. Packaging

| Aspect | BC5CDR (training) | Pill packaging (our use) |
|--------|-------------------|--------------------------|
| Text style | Scientific prose | Formulaic labels |
| Length | Full abstracts (~200 words) | Short labels (~5-20 words) |
| Chemical mentions | In sentence context | Standalone, prominent |
| Brand names | Rare | Very common |
| Salt forms | Part of scientific name | Separated on packaging |
| OCR artifacts | None | Common (rn→m, 0→o, etc.) |

## Our Pipeline

```
Raw OCR text
    → ocr_cleaner.py (fix rn→m, 0→o, ligatures, whitespace)
    → ner_model.py (PharmaDetect with manual sub-word merging)
    → drug_analyzer.py (filter CHEM labels, dedupe, skip single-char/punctuation)
    → rxnorm_client.py (validate against RxNorm, get rxcui)
    → [if NER finds nothing] rxnorm fallback (approximate term search)
```

The benchmark tests the first three steps (OCR cleaner → NER → basic filtering)
without RxNorm validation, to isolate the NER model's behavior on packaging text.

## Results

### By Noise Level (500-case samples)

| Noise | Precision | Recall | F1 | Detection |
|-------|-----------|--------|------|-----------|
| **none** (clean) | **46.9%** | **84.4%** | **60.3%** | 99.6% |
| **light** (5-15% char errors) | 44.9% | 79.8% | 57.5% | 99.8% |
| **heavy** (40% errors + splits) | 26.2% | 53.5% | 35.2% | 99.8% |

Detection rate = percentage of cases where NER found at least one entity.

### By Category (clean text, 500 cases)

| Category | N | Precision | Recall | F1 | TP | FP | FN |
|----------|---|-----------|--------|-----|-----|-----|-----|
| single_ingredient | 279 | 41% | 86% | 55% | 239 | 347 | 40 |
| dual_ingredient | 155 | 49% | 85% | 62% | 261 | 270 | 47 |
| multi_ingredient | 66 | 54% | 82% | 65% | 170 | 143 | 37 |

### Interpretation

**Recall is strong (84%).** The model finds the active ingredient in most
cases. Multi-ingredient labels are slightly harder (82%) due to more
complex text. Under light OCR noise, recall drops only to 80% — the
model is reasonably robust to minor distortion.

**Precision is poor (47%).** The model tags brand names, manufacturer
names, salt forms, and dosage form words as chemical entities. This is
correct per BC5CDR training ("find all chemicals") but wrong for our use
case ("find active pharmaceutical ingredients only").

**Heavy noise halves recall (54%).** Mid-word splits (`Bevacizu mab`)
and character corruption (`Metforrnin`) break the tokenizer. This is
the target for Phase 4 (OCR Modernization with dictionary-backed fuzzy
matching).

## False Positive Analysis

All false positives fall into predictable categories:

### 1. Brand Names
The model tags brand names as chemical entities: Augmentin, Avastin,
Allegra, Lipitor, etc. These are the medicine's trade names, not active
ingredients.

### 2. Salt Forms
The model tags salt/counter-ion names separately: Sodium, Hydrochloride,
Calcium, Phosphate, Maleate, Potassium. These appear in compositions
like "Atorvastatin Calcium" but are not the active drug.

### 3. Manufacturer Names
Pharmaceutical company names occasionally get tagged: "Cipla", "Lupin",
names that look chemical-like to the model.

### 4. Dosage Form Words
Words like "Tablet", "Capsule", "Syrup", "Injection" sometimes get
tagged, especially in compact label layouts.

## Noise Degradation Analysis

| Metric | None → Light | Light → Heavy |
|--------|-------------|---------------|
| Recall | 84% → 80% (−4pp) | 80% → 54% (−26pp) |
| Precision | 47% → 45% (−2pp) | 45% → 26% (−19pp) |
| F1 | 60% → 58% (−3pp) | 58% → 35% (−23pp) |

Light noise has minimal impact — the OCR cleaner handles common `o→0`
and `l→1` substitutions. Heavy noise causes severe degradation because:

- **Mid-word splits** break tokenization (`Amoxy cillin` becomes two tokens)
- **m→rn corruption** in drug names (`Metforrnin`) escapes the cleaner's
  limited regex patterns
- **All-caps text** shifts token distributions away from training data

## Comparison with Published Benchmarks

| Benchmark | Precision | Recall | F1 |
|-----------|-----------|--------|-----|
| BC5CDR-CHEM (published) | 95.1% | 96.6% | 95.8% |
| Our packaging — clean | 46.9% | 84.4% | 60.3% |
| Our packaging — light noise | 44.9% | 79.8% | 57.5% |
| Our packaging — heavy noise | 26.2% | 53.5% | 35.2% |

The precision gap (95% → 47%) reflects a **task mismatch**, not model
quality. BC5CDR measures "find all chemicals" — we measure "find only
active pharmaceutical ingredients." The recall gap (97% → 84%) reflects
the domain shift from clean scientific text to formulaic packaging labels.

## Remediation Plan

| Phase | Target | Expected Impact |
|-------|--------|-----------------|
| **Phase 2: Entity Linking** | Filter NER output through DrugBank to reject non-drug entities | Precision 47% → ~85%+ |
| **Phase 3: Fallback** | DrugBank fuzzy search when NER finds 0 entities | Recall +5-10% on edge cases |
| **Phase 4: OCR Modernization** | Dictionary-backed fuzzy correction before NER | Heavy-noise recall 54% → ~75%+ |

See `docs/plans/phase{2,3,4}_*.md` for detailed designs.

## Reproducing

```bash
# Generate dataset (once)
uv run python eval/prepare_hf_dataset.py                  # clean
uv run python eval/prepare_hf_dataset.py --noise light     # light OCR noise
uv run python eval/prepare_hf_dataset.py --noise heavy     # heavy OCR noise

# Run benchmark
uv run python eval/benchmark.py                    # full dataset
uv run python eval/benchmark.py --limit 500        # quick run
uv run python eval/benchmark.py --with-rxnorm      # full pipeline (needs network)
uv run python eval/benchmark.py -v                 # per-case details
```

Results are written to `eval/results.json`.

## References

- [OpenMed NER paper](https://arxiv.org/abs/2508.01630) — Panahi, 2025
- [BC5CDR corpus](https://pmc.ncbi.nlm.nih.gov/articles/PMC4860626/) — Li et al., 2016
- [Bio_Discharge_Summary_BERT](https://huggingface.co/emilyalsentzer/Bio_Discharge_Summary_BERT) — Alsentzer et al.
- [PharmaDetect-BioPatient-108M](https://huggingface.co/OpenMed/OpenMed-NER-PharmaDetect-BioPatient-108M) — OpenMed
- [MattBastar/Medicine_Details](https://huggingface.co/datasets/MattBastar/Medicine_Details) — HuggingFace dataset
