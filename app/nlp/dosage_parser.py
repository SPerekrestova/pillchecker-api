"""Regex-based dosage extraction from packaging text.

Medicine packaging follows legally regulated formats, making dosages
highly predictable with regex. Handles single dosages (400 mg),
compound dosages (10 mg/5 ml), and per-unit dosages (500 mg/tablet).
"""

import re
from dataclasses import dataclass

# Units commonly found on medicine packaging
_UNITS = r"(?:mg|mcg|µg|g|ml|mL|IU|%|mmol|mEq)"

# Core pattern: number + optional space + unit
# Handles: "400 mg", "0.5g", "10mcg", "200mg"
_SIMPLE = rf"(\d+\.?\d*)\s*({_UNITS})"

# Compound: number+unit / number+unit
# Handles: "10 mg/5 ml", "500mg/5ml", "200mg/ml"
_COMPOUND = rf"(\d+\.?\d*)\s*({_UNITS})\s*/\s*(\d*\.?\d*)\s*({_UNITS})"

# Per-unit: number+unit / form
# Handles: "500 mg/tablet", "10mg/capsule", "100mg/dose"
_FORMS = r"(?:tablet|capsule|dose|sachet|suppository|patch|vial|ampoule|puff)"
_PER_UNIT = rf"(\d+\.?\d*)\s*({_UNITS})\s*/\s*({_FORMS})"

# Percentage: "0.1%", "5 %"
_PERCENT = r"(\d+\.?\d*)\s*%"

DOSAGE_PATTERN = re.compile(
    rf"(?:{_COMPOUND})|(?:{_PER_UNIT})|(?:{_SIMPLE})|(?:{_PERCENT})",
    re.IGNORECASE,
)


@dataclass
class Dosage:
    raw: str        # Original matched text, e.g. "400 mg"
    value: float    # Numeric value, e.g. 400.0
    unit: str       # Unit string, e.g. "mg"
    per_value: float | None = None   # Denominator value for compound
    per_unit: str | None = None      # Denominator unit for compound


def extract_dosages(text: str) -> list[Dosage]:
    """Extract all dosage mentions from text.

    Returns a list of Dosage objects with parsed numeric values and units.
    """
    dosages = []
    for match in DOSAGE_PATTERN.finditer(text):
        raw = match.group(0)

        # Try compound first (groups 1-4)
        if match.group(1) and match.group(4):
            dosages.append(Dosage(
                raw=raw,
                value=float(match.group(1)),
                unit=match.group(2),
                per_value=float(match.group(3)) if match.group(3) else 1.0,
                per_unit=match.group(4),
            ))
        # Try per-unit (groups 5-7)
        elif match.group(5):
            dosages.append(Dosage(
                raw=raw,
                value=float(match.group(5)),
                unit=match.group(6),
                per_unit=match.group(7),
            ))
        # Try simple (groups 8-9)
        elif match.group(8):
            dosages.append(Dosage(
                raw=raw,
                value=float(match.group(8)),
                unit=match.group(9),
            ))
        # Percentage (group 10)
        elif match.group(10):
            dosages.append(Dosage(
                raw=raw,
                value=float(match.group(10)),
                unit="%",
            ))

    return dosages
