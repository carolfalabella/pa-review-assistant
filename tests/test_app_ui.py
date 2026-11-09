"""Runs the Streamlit app headlessly with Streamlit's own test harness.

Skipped where Streamlit isn't installed. Uses a saved run, so no network.
"""

import json
import shutil

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from src.config import ROOT  # noqa: E402
from src.prompts import PROMPT_VERSION  # noqa: E402

from .conftest import FIXTURE  # noqa: E402


@pytest.fixture
def app(tmp_path, monkeypatch):
    saved = tmp_path / "saved"
    saved.mkdir()
    rec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rec["prompt_version"] = PROMPT_VERSION  # the app only replays runs made with the current prompt
    (saved / "fixture.json").write_text(json.dumps(rec), encoding="utf-8")
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    monkeypatch.setenv("DEMO_RECEIPT_TIME", "2026-11-02T09:00:00-05:00")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception
    at.sidebar.radio[0].set_value("Saved run").run()
    at.sidebar.button[0].click().run()  # Run review
    assert not at.exception
    return at


def _text(at) -> str:
    return " ".join(m.value for m in at.markdown) + " " + " ".join(w.value for w in at.warning)


def test_saved_run_shows_banner_and_all_four_statuses(app):
    text = _text(app)
    assert "SAVED RUN" in text
    for label in ("Met", "Not met", "Missing"):
        assert f"**{label}**" in text


def test_approve_is_disabled_and_there_is_no_deny_button(app):
    labels = [b.label for b in app.button]
    approve = next(b for b in app.button if b.label == "Approve")
    assert approve.disabled
    assert not any("deny" in lbl.lower() or "partial" in lbl.lower() for lbl in labels)


def test_audit_tab_reports_an_intact_chain(app):
    assert any("intact" in m.value for m in app.markdown)


def _decision_box(at, rule_id):
    return next(s for s in at.selectbox if s.label.startswith(f"Your decision for {rule_id}"))


def _save_button(at, index):
    return [b for b in at.button if b.label == "Save review"][index]


def test_override_without_a_reason_is_refused_in_the_app(app):
    # Regression (Nov 9): changing the status without a reason used to save as a confirm.
    _decision_box(app, "C1").set_value("not_met")
    _save_button(app, 0).click().run()
    assert any("An override of C1 needs a reason" in e.value for e in app.error)
    assert not any("Overridden by" in s.value or "Confirmed by" in s.value for s in app.success)


def test_keeping_the_ai_result_saves_a_confirm(app):
    _save_button(app, 0).click().run()  # C1 decision starts at the AI result, Met
    assert any("Confirmed by demo-nurse" in s.value for s in app.success)
