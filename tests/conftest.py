"""Shared test helpers. No test calls a real model or the network."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.config import ROOT, load_settings
from src.llm import LLMError, LLMResponse

DATA = ROOT / "data" / "synthetic"
FIXTURE = Path(__file__).parent / "fixtures" / "case_001_fixture.json"


class FakeProvider:
    """Returns prepared responses per call. A value that is an Exception is raised."""

    name = "fake"

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[str] = []

    def generate_json(self, call_name, system, user, schema):
        self.calls.append(call_name)
        value = self.responses[call_name]
        if isinstance(value, Exception):
            raise value
        text = value if isinstance(value, str) else json.dumps(value)
        return LLMResponse(text=text, provider="fake", model="fake-model", seconds=0.0)


@pytest.fixture
def fixture_responses() -> dict:
    """The hand-written golden responses, as dicts, safe to modify per test."""
    rec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {k: json.loads(v) for k, v in rec["responses"].items()}


@pytest.fixture
def settings(tmp_path):
    return load_settings().with_(runs_dir=tmp_path, receipt_time="2026-11-02T09:00:00-05:00",
                                 retry_waits=(0, 0, 0, 0))


@pytest.fixture
def run(settings):
    """run(responses, case='case_001') -> pipeline result using a FakeProvider."""
    from src.pipeline import run_case

    def _run(responses, case="case_001"):
        return run_case(DATA / f"{case}.pdf", settings, provider=FakeProvider(copy.deepcopy(responses)))

    return _run


def rule(result, rule_id):
    return next(r for r in result["rules"] if r["id"] == rule_id)


def element(result, element_id):
    return next(e for r in result["rules"] for e in r["elements"] if e["element_id"] == element_id)


__all__ = ["FakeProvider", "LLMError", "rule", "element", "DATA", "FIXTURE"]
