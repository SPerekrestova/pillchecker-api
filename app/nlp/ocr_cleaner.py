"""OCR text preprocessing for pharmaceutical text.

Normalizes common OCR artifacts before passing text to the NER model.
Conservative by design — only applies corrections with high confidence
to avoid corrupting legitimate text.
"""

import re
import unicodedata

# Zero-width and invisible characters to strip
_INVISIBLE_CHARS = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")

# Soft hyphens
_SOFT_HYPHEN = re.compile(r"\u00ad")

# Whitespace normalization: tabs, newlines, multiple spaces → single space
_WHITESPACE = re.compile(r"[\t\n\r\f\v]+| {2,}")

# Smart quotes → straight quotes
_SMART_QUOTES = {
    "\u2018": "'", "\u2019": "'",  # single
    "\u201c": '"', "\u201d": '"',  # double
}

# Common ligatures
_LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
}

# OCR digit→letter substitutions that commonly affect drug names.
# Only applied when surrounded by letters (not in "400mg").
_DIGIT_IN_WORD = [
    (re.compile(r"(?<=[a-zA-Z])0(?=[a-zA-Z])"), "o"),  # metf0rmin → metformin
    (re.compile(r"(?<=[a-zA-Z])1(?=[a-zA-Z])"), "l"),  # a1prazolam → alprazolam
]

# Known OCR "rn" → "m" patterns in drug names (conservative list)
_RN_TO_M_PATTERNS = [
    (re.compile(r"Aceta\s+rninophen", re.IGNORECASE), "Acetaminophen"),  # space-split acetaminophen
    (re.compile(r"rninophen", re.IGNORECASE), "minophen"),  # acetaminophen
    (re.compile(r"rnidazole", re.IGNORECASE), "midazole"),  # metronidazole
    (re.compile(r"rnetforrnin", re.IGNORECASE), "metformin"),
    (re.compile(r"(?<=[Aa])rnlodipine", re.IGNORECASE), "mlodipine"),  # amlodipine
]


def clean(text: str) -> str:
    """Clean OCR artifacts from pharmaceutical text.

    Conservative: only applies high-confidence corrections.
    Preserves digits in dosage contexts (e.g., '400mg').
    """
    if not text:
        return text

    # Strip invisible characters
    text = _INVISIBLE_CHARS.sub("", text)

    # Remove soft hyphens
    text = _SOFT_HYPHEN.sub("", text)

    # Expand ligatures
    for lig, replacement in _LIGATURES.items():
        text = text.replace(lig, replacement)

    # Replace smart quotes
    for smart, straight in _SMART_QUOTES.items():
        text = text.replace(smart, straight)

    # Digit→letter substitutions (only between letters)
    for pattern, replacement in _DIGIT_IN_WORD:
        text = pattern.sub(replacement, text)

    # Known rn→m patterns
    for pattern, replacement in _RN_TO_M_PATTERNS:
        text = pattern.sub(replacement, text)

    # Normalize whitespace last
    text = _WHITESPACE.sub(" ", text).strip()

    return text
