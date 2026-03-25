#!/usr/bin/env python3
"""Smoke test for drug interaction detection against live/local service.

Validates that known dangerous drug pairs are correctly detected.
Intended to run after DB updates and in CI after Docker build.

Usage:
    python scripts/smoke_test_interactions.py [BASE_URL]

Default BASE_URL: http://localhost:8000
Set API_KEY env var for authenticated endpoints.
"""

import os
import sys
import httpx

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
API_KEY = os.environ.get("API_KEY", "")

MUST_DETECT = [
    ("warfarin", "ibuprofen", "major bleeding risk"),
    ("phenelzine", "fluoxetine", "serotonin syndrome — contraindicated"),
    ("ritonavir", "simvastatin", "rhabdomyolysis — contraindicated"),
    ("methotrexate", "trimethoprim", "bone marrow suppression"),
]

MUST_BE_SAFE = [
    ("acetaminophen", "amoxicillin", "no known interaction"),
]


def check_pair(drug_a: str, drug_b: str, expected_safe: bool, reason: str) -> bool:
    """Check a single drug pair. Returns True if test passes."""
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY

    resp = httpx.post(
        f"{BASE_URL}/interactions",
        json={"drugs": [drug_a, drug_b]},
        headers=headers,
        timeout=30,
    )

    if resp.status_code != 200:
        print(f"  FAIL: HTTP {resp.status_code}")
        return False

    data = resp.json()
    actual_safe = data.get("safe")

    if actual_safe == expected_safe:
        print(f"  PASS: {drug_a} + {drug_b} → safe={actual_safe} ({reason})")
        return True
    else:
        print(f"  FAIL: {drug_a} + {drug_b} → safe={actual_safe}, expected={expected_safe} ({reason})")
        if data.get("interactions"):
            for ix in data["interactions"]:
                print(f"        {ix['severity']}: {ix['description'][:80]}")
        return False


def main():
    print(f"Smoke testing interactions at {BASE_URL}\n")

    passed = 0
    failed = 0

    print("=== Must detect interaction (safe=false) ===")
    for drug_a, drug_b, reason in MUST_DETECT:
        if check_pair(drug_a, drug_b, expected_safe=False, reason=reason):
            passed += 1
        else:
            failed += 1

    print("\n=== Must be safe (safe=true) ===")
    for drug_a, drug_b, reason in MUST_BE_SAFE:
        if check_pair(drug_a, drug_b, expected_safe=True, reason=reason):
            passed += 1
        else:
            failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")

    if failed > 0:
        print("\nSMOKE TEST FAILED — known dangerous interactions not detected!")
        sys.exit(1)
    else:
        print("\nAll smoke tests passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
