"""Download MattBastar/Medicine_Details from HuggingFace and build a labeled benchmark dataset.

Synthesizes realistic OCR-like text from packaging fields (brand name,
composition, manufacturer, uses) to simulate what a camera photo of a
pill pack label would produce after OCR processing.

OCR noise is modeled on real pharmaceutical OCR failure modes:
  - m↔rn confusion (Metformin → Metforrnin, rnetforrnin)
  - I/l/1 confusion at word start and inside words
  - o/O/0 confusion inside words
  - cl↔d confusion
  - mg→rng in dosage strings
  - word splits from line-wrap artifacts (Acetaminophen → Aceta minophen)
  - extra whitespace, missing spaces, random line breaks

Source: https://huggingface.co/datasets/MattBastar/Medicine_Details

Usage:
    uv run python eval/prepare_hf_dataset.py                  # clean label text
    uv run python eval/prepare_hf_dataset.py --noise light     # light OCR artifacts
    uv run python eval/prepare_hf_dataset.py --noise heavy     # heavy OCR distortion
    uv run python eval/prepare_hf_dataset.py --limit 500       # smaller sample
"""

import csv
import json
import random
import re
import urllib.request
from pathlib import Path

DATASET_URL = (
    "https://huggingface.co/datasets/MattBastar/Medicine_Details"
    "/resolve/main/Medicine_Details.csv"
)
OUTPUT_PATH = Path(__file__).parent / "hf_medicine_dataset.json"


# ---------------------------------------------------------------------------
# OCR noise — modeled on real pharmaceutical label OCR failures
# ---------------------------------------------------------------------------

# Bigram substitutions (checked first, order matters)
_BIGRAM_SUBS = [
    ("rn", "m"),    # rn→m: common reverse confusion
    ("cl", "d"),    # cl→d: font-dependent ligature
]

# Single-char substitutions applied inside words (between letters)
_INTERIOR_SUBS = [
    ("m", "rn"),    # Metformin → Metforrnin (THE classic OCR error)
    ("l", "1"),     # Alprazolam → A1prazolam
    ("o", "0"),     # Omeprazole → 0meprazole
    ("O", "0"),     # LOSARTAN → L0SARTAN
]

# Word-initial substitutions (applied to first character)
_INITIAL_SUBS = [
    ("I", "l"),     # Ibuprofen → lbuprofen
    ("l", "I"),     # losartan → Iosartan (less common, but real)
]

# Dosage-string corruptions
_DOSAGE_SUBS = [
    (re.compile(r"(\d+)\s*mg"), r"\1rng"),      # 500mg → 500rng
    (re.compile(r"(\d+)\s*mcg"), r"\1 rncg"),   # 50mcg → 50 rncg
    (re.compile(r"(\d+)\s*ml"), r"\g<1>rnl"),   # 5ml → 5rnl
]


def _corrupt_word(word: str, rate: float, rng: random.Random) -> str:
    """Apply pharma-specific OCR substitutions to a single word."""
    if len(word) <= 2 or not word[0].isalpha():
        return word

    chars = list(word)

    # Word-initial substitution
    if rng.random() < rate:
        for old, new in _INITIAL_SUBS:
            if chars[0] == old:
                chars[0] = new
                break

    # Interior substitutions (skip first and last char)
    i = 1
    while i < len(chars) - 1:
        if rng.random() < rate:
            # Try bigram first
            bigram = chars[i] + chars[i + 1] if i + 1 < len(chars) else ""
            matched = False
            for old, new in _BIGRAM_SUBS:
                if bigram == old:
                    chars[i] = new
                    chars[i + 1] = ""
                    matched = True
                    i += 2
                    break
            if matched:
                continue
            # Single-char
            for old, new in _INTERIOR_SUBS:
                if chars[i] == old:
                    chars[i] = new
                    break
        i += 1

    return "".join(chars)


def _corrupt_spacing(text: str, rate: float, rng: random.Random) -> str:
    """Insert spacing artifacts: mid-word splits, extra spaces, line breaks."""
    words = text.split()
    result = []
    for word in words:
        # Mid-word split on long words (simulates line-wrap OCR artifact)
        if len(word) > 7 and rng.random() < rate * 0.5:
            split_pos = rng.randint(3, len(word) - 3)
            word = word[:split_pos] + " " + word[split_pos:]

        result.append(word)

        # Inter-word artifact: extra space or line break
        if rng.random() < rate * 0.3:
            result.append(rng.choice(["  ", "   ", "\n", " \n"]))
        else:
            result.append(" ")

    return "".join(result).strip()


def _corrupt_dosages(text: str, rate: float, rng: random.Random) -> str:
    """Corrupt dosage strings (mg→rng, mcg→rncg)."""
    for pattern, repl in _DOSAGE_SUBS:
        if rng.random() < rate:
            text = pattern.sub(repl, text, count=1)  # corrupt at most one occurrence
    return text


def add_ocr_noise(text: str, level: str, rng: random.Random) -> str:
    """Add pharmaceutical OCR artifacts to text.

    Levels:
        none  — no changes
        light — ~15% of words get one substitution, rare spacing issues
        heavy — ~40% of words corrupted, dosage errors, spacing artifacts
    """
    if level == "none":
        return text

    rate = 0.15 if level == "light" else 0.40

    # Corrupt individual words
    words = text.split()
    corrupted_words = [_corrupt_word(w, rate, rng) for w in words]
    text = " ".join(corrupted_words)

    # Corrupt dosage strings
    text = _corrupt_dosages(text, rate * 0.5, rng)

    # Spacing artifacts (heavy only adds mid-word splits)
    if level == "heavy":
        text = _corrupt_spacing(text, rate, rng)

    # Occasional all-caps (labels printed in uppercase)
    if rng.random() < (0.05 if level == "light" else 0.15):
        text = text.upper()

    return text


# ---------------------------------------------------------------------------
# Packaging text synthesis
# ---------------------------------------------------------------------------

_LABEL_TEMPLATES = [
    # Tablet/capsule blister pack — most common
    "{name}\nEach {form} contains:\n{composition_block}\n{manufacturer}",
    # Indian-style detailed label
    "{name}\nComposition: {composition_line}\nMfg: {manufacturer}\nFor: {uses_short}",
    # Compact box label
    "{name}\n{composition_line}\n{manufacturer}",
    # Prescription-style with Rx
    "Rx only\n{name}\n({composition_line})\n{manufacturer}",
    # Syrup/liquid label
    "{name}\nEach 5ml contains:\n{composition_block}\n{manufacturer}\nStore below 25°C",
]


def build_composition_block(composition: str) -> str:
    """Expand composition into multi-line ingredient listing."""
    parts = composition.split("+")
    lines = []
    for part in parts:
        part = part.strip()
        match = re.match(r"^([A-Za-z][A-Za-z\s\-/]+?)\s*\(([^)]+)\)", part)
        if match:
            name, dose = match.group(1).strip(), match.group(2).strip()
            lines.append(f"{name} {dose}")
        else:
            lines.append(part)
    return "\n".join(lines)


def extract_form(medicine_name: str) -> str:
    """Extract dosage form from medicine name."""
    lower = medicine_name.lower()
    for form in ["tablet", "capsule", "syrup", "injection", "cream",
                  "gel", "drops", "inhaler", "suspension", "ointment",
                  "lozenges", "respules", "spray", "solution"]:
        if form in lower:
            return form
    return "tablet"


def synthesize_label(row: dict, rng: random.Random) -> str:
    """Synthesize realistic packaging label text from dataset row."""
    name = row["Medicine Name"].strip()
    composition = row.get("Composition", "")
    manufacturer = row.get("Manufacturer", "")
    uses = row.get("Uses", "")
    form = extract_form(name)

    composition_line = composition
    composition_block = build_composition_block(composition)
    uses_short = uses[:60] if uses else ""

    template = rng.choice(_LABEL_TEMPLATES)
    return template.format(
        name=name,
        form=form,
        composition_line=composition_line,
        composition_block=composition_block,
        manufacturer=manufacturer,
        uses_short=uses_short,
    )


# ---------------------------------------------------------------------------
# Ingredient parsing
# ---------------------------------------------------------------------------

def parse_ingredients(composition: str) -> list[str]:
    """Extract ingredient names from composition string.

    "Amoxycillin (500mg) + Clavulanic Acid (125mg)" -> ["Amoxycillin", "Clavulanic Acid"]
    """
    parts = composition.split("+")
    names = []
    for part in parts:
        part = part.strip()
        match = re.match(r"^([A-Za-z][A-Za-z\s\-/]+?)\s*\(", part)
        if match:
            name = match.group(1).strip()
            if name:
                names.append(name)
    return names


def categorize(n_ingredients: int) -> str:
    if n_ingredients == 1:
        return "single_ingredient"
    if n_ingredients == 2:
        return "dual_ingredient"
    return "multi_ingredient"


def download_csv(url: str, dest: Path) -> Path:
    if dest.exists():
        print(f"Using cached {dest.name}")
        return dest
    print("Downloading from HuggingFace...")
    urllib.request.urlretrieve(url, dest)
    print(f"Saved to {dest.name}")
    return dest


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Prepare HF medicine benchmark dataset")
    parser.add_argument("--limit", type=int, default=0, help="Max cases (0 = all)")
    parser.add_argument("--noise", choices=["none", "light", "heavy"], default="none",
                        help="OCR noise level (default: none)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    rng = random.Random(args.seed)

    csv_path = Path(__file__).parent / ".medicine_details_cache.csv"
    download_csv(DATASET_URL, csv_path)

    dataset = []
    skipped = 0

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            composition = row.get("Composition", "")
            ingredients = parse_ingredients(composition)
            medicine_name = row.get("Medicine Name", "").strip()

            if not medicine_name or not ingredients:
                skipped += 1
                continue

            label_text = synthesize_label(row, rng)
            ocr_text = add_ocr_noise(label_text, args.noise, rng)

            dataset.append(
                {
                    "id": f"hf-{i:05d}",
                    "category": categorize(len(ingredients)),
                    "ocr_text": ocr_text,
                    "expected_names": ingredients,
                    "source_composition": composition,
                }
            )

    if args.limit > 0:
        dataset = dataset[: args.limit]

    OUTPUT_PATH.write_text(json.dumps(dataset, indent=2, ensure_ascii=False))

    categories = {}
    for case in dataset:
        cat = case["category"]
        categories[cat] = categories.get(cat, 0) + 1

    print(f"\nWrote {len(dataset)} cases to {OUTPUT_PATH.name}")
    print(f"Skipped {skipped} rows (no name or no parseable ingredients)")
    print(f"Noise level: {args.noise}")
    print("\nBy category:")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")

    # Show samples
    print("\nSample entries:")
    for case in dataset[:3]:
        print(f"\n--- {case['id']} ({case['category']}) ---")
        print(f"OCR text:\n{case['ocr_text']}")
        print(f"Expected: {case['expected_names']}")


if __name__ == "__main__":
    main()
