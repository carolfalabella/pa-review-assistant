"""Rule Selection, demo stand-in.

Production: exact lookup in a versioned rule registry by service, line of
business, state, and date of service. Never a similarity search.
Demo: one fixed JSON file of four illustrative rules.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import ROOT

CRITERIA_FILE = ROOT / "criteria" / "lumbar_mri_v1.json"


def load_criteria(path: Path = CRITERIA_FILE) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    ids = [e["id"] for c in data["criteria"] for e in c["elements"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate part IDs in the rules file")
    return data


def element_ids(criteria: dict) -> list[str]:
    return [e["id"] for c in criteria["criteria"] for e in c["elements"]]


def criteria_version(criteria: dict) -> str:
    return f"{criteria['criteria_set_id']}@{criteria['version']}"
