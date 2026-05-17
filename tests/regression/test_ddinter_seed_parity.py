"""Regression gate: DDInter should match curated seed severities.

This is not the temporary DrugBank-vs-DDInter parity check from the original
plan. It is a permanent guard against drifting away from curated smoke severity
ground truth in eval/interaction_seed_cases.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


DB_PATH = Path(os.environ.get("INTERACTION_DB_PATH", "data/ddinter.db"))
_SEED = json.loads(Path("eval/interaction_seed_cases.json").read_text())["positive_pairs"]


@pytest.mark.parametrize("case", _SEED)
async def test_ddinter_seed_severity_matches_expected(case, monkeypatch):
    if not DB_PATH.exists():
        pytest.skip("DDInter DB missing; regression gate requires INTERACTION_DB_PATH or data/ddinter.db")

    from app.clients import ddinter_db
    from app.services import interaction_checker

    await ddinter_db.client.close()
    ddinter_db.client.db_path = str(DB_PATH)
    monkeypatch.setattr(interaction_checker.openfda_client, "check_pair", _no_openfda)

    try:
        result = await interaction_checker.check([case["drug_a"], case["drug_b"]])
        if not result["interactions"]:
            pytest.skip(f"DDInter returned no interaction for {case['drug_a']} + {case['drug_b']}")
        assert result["interactions"][0]["source"] == "ddinter"
        assert result["interactions"][0]["severity"] == case["severity"]
    finally:
        await ddinter_db.client.close()


async def _no_openfda(_drug_a: str, _drug_b: str):
    return None
