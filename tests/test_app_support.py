"""App logic that doesn't need Streamlit: background runs, saved-run choice, highlighting."""

import json

from src.app_support import LiveJob, find_saved_run, format_hours, highlight_html
from src.audit import AuditLog
from src.ingest import read_pages
from src.prompts import PROMPT_VERSION

from .conftest import DATA, FIXTURE


def _write(path, case_id, prompt_version, created_at):
    path.write_text(json.dumps({"case_id": case_id, "prompt_version": prompt_version,
                                "created_at": created_at, "responses": {}}), encoding="utf-8")


def test_saved_run_must_match_case_and_current_prompt(tmp_path):
    _write(tmp_path / "old_prompt.json", "case_001", "2026-11-07.1", "2026-11-09T00:00")
    _write(tmp_path / "other_case.json", "case_002_missing", PROMPT_VERSION, "2026-11-09T00:00")
    _write(tmp_path / "older.json", "case_001", PROMPT_VERSION, "2026-11-08T09:00")
    _write(tmp_path / "newest.json", "case_001", PROMPT_VERSION, "2026-11-08T11:00")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert find_saved_run(tmp_path, "case_001", PROMPT_VERSION).name == "newest.json"
    assert find_saved_run(tmp_path, "case_003_not_met", PROMPT_VERSION) is None


def test_highlight_marks_the_quote_and_escapes_html():
    html_text, found = highlight_html("Pain <b>6/10</b>.\nRadicular symptoms persist.", "Radicular symptoms persist")
    assert found
    assert "&lt;b&gt;" in html_text and "<b>" not in html_text
    assert "<mark>Radicular symptoms persist</mark>" in html_text


def test_highlight_reports_a_quote_that_is_not_on_the_page():
    page = {p.number: p.text for p in read_pages(DATA / "case_001.pdf")}[7]
    _, found = highlight_html(page, "Patient reports no relief after 12 weeks")
    assert not found


def test_live_job_runs_in_the_background_and_returns_a_result(settings):
    from src.llm import SavedProvider
    s = settings.with_(provider="saved", saved_run=FIXTURE)
    job = LiveJob(DATA / "case_001.pdf", s, AuditLog(s.runs_dir / "audit.jsonl")).start()
    job.thread.join(timeout=30)
    assert job.done() and job.error is None
    assert [r["status"] for r in job.result["rules"]] == ["met", "met", "not_met", "missing"]
    assert SavedProvider  # imported to show the provider used by PROVIDER=saved


def test_live_job_reports_unexpected_errors(settings, tmp_path):
    job = LiveJob(tmp_path / "missing.pdf", settings, AuditLog(tmp_path / "a.jsonl")).start()
    job.thread.join(timeout=30)
    assert job.result is None and job.error


def test_format_hours():
    assert format_hours(168) == "7 d 0 h left"
    assert format_hours(5.2) == "5 h left"
    assert format_hours(-3) == "overdue by 3 h"
