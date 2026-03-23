"""Deterministic severity parser for DrugBank interaction descriptions.

DrugBank descriptions follow ~6 known sentence templates. This parser
matches against those templates to classify severity without ML inference.

Use this for DrugBank interactions. For unstructured text (e.g., OpenFDA),
use severity_classifier.py instead.
"""

import re

# Templates ordered by specificity — first match wins.
_TEMPLATES: list[tuple[re.Pattern, str]] = [
    # "The risk or severity of X can be increased/decreased" → major
    (re.compile(r"risk or severity of .+ can be (increased|decreased)", re.IGNORECASE), "major"),

    # "may increase the X activities" → moderate
    (re.compile(r"may increase the .+ activities", re.IGNORECASE), "moderate"),

    # "may decrease the X activities" → minor
    (re.compile(r"may decrease the .+ activities", re.IGNORECASE), "minor"),

    # "serum concentration .+ can be increased/decreased" → moderate
    (re.compile(r"serum concentration .+ can be (increased|decreased)", re.IGNORECASE), "moderate"),

    # "metabolism .+ can be increased/decreased" → moderate
    (re.compile(r"metabolism .+ can be (increased|decreased)", re.IGNORECASE), "moderate"),

    # "therapeutic efficacy .+ can be decreased" → minor
    (re.compile(r"therapeutic efficacy .+ can be (decreased|increased)", re.IGNORECASE), "minor"),

    # "excretion .+ can be increased/decreased" → moderate
    (re.compile(r"excretion .+ can be (increased|decreased)", re.IGNORECASE), "moderate"),

    # "absorption .+ can be increased/decreased" → moderate
    (re.compile(r"absorption .+ can be (increased|decreased)", re.IGNORECASE), "moderate"),
]


def parse_severity(description: str | None) -> str:
    """Parse severity from a DrugBank interaction description template.

    Returns 'major', 'moderate', 'minor', or 'unknown' if no template matches.
    """
    if not description:
        return "unknown"

    for pattern, severity in _TEMPLATES:
        if pattern.search(description):
            return severity

    return "unknown"
