"""Logic for the Streamlit app that doesn't depend on Streamlit, so it can be tested.

- LiveJob: runs the pipeline in a background thread, so the page stays
  responsive and can offer the saved-run fallback while a live call waits.
- find_saved_run: picks the newest saved run for this packet AND the current
  prompt version, so the fallback always matches the code being shown.
- highlight_html: shows a source page with the cited quote highlighted.
"""

from __future__ import annotations

import html
import json
import threading
import time
from pathlib import Path

from .audit import AuditLog
from .config import Settings
from .pipeline import run_case
from .verify import locate_quote

STATUS_LABEL = {
    "met": "Met",
    "not_met": "Not met",
    "missing": "Missing",
    None: "No result",
}
STATUS_MEANING = {
    "met": "The record supports this.",
    "not_met": "The record contains contrary evidence. A potential issue for clinician review, not a denial.",
    "missing": "The record doesn't address this. Consider requesting information.",
    None: "The AI returned no usable result. Review the source directly.",
}
STATUS_COLOR = {"met": "green", "not_met": "red", "missing": "orange", None: "gray"}

FIELD_LABEL = {
    "diagnosis": "Diagnosis",
    "requested_service": "Requested service",
    "relevant_history": "Relevant history",
    "supporting_findings": "Supporting findings",
}


class LiveJob:
    """One pipeline run in a background thread. The thread never touches the UI;
    the page polls done(), elapsed(), and events."""

    def __init__(self, pdf_path: Path, settings: Settings, audit: AuditLog):
        self.pdf_path = pdf_path
        self.settings = settings
        self.audit = audit
        self.events: list[str] = []
        self.result: dict | None = None
        self.error: str | None = None
        self.started = time.monotonic()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "LiveJob":
        self.thread.start()
        return self

    def _on_wait(self, call: str, attempt: int, wait: int, reason: str) -> None:
        self.events.append(f"{call}: {reason}. Retrying in {wait}s (attempt {attempt}).")

    def _run(self) -> None:
        try:
            self.result = run_case(self.pdf_path, self.settings, audit=self.audit, on_wait=self._on_wait)
        except Exception as exc:  # anything unexpected is shown, never swallowed
            self.error = f"{type(exc).__name__}: {exc}"

    def done(self) -> bool:
        return not self.thread.is_alive()

    def elapsed(self) -> float:
        return time.monotonic() - self.started


def find_saved_run(saved_dir: Path, case_id: str, prompt_version: str) -> Path | None:
    best, best_time = None, ""
    for path in Path(saved_dir).glob("*.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if rec.get("case_id") == case_id and rec.get("prompt_version") == prompt_version:
            if rec.get("created_at", "") > best_time:
                best, best_time = path, rec.get("created_at", "")
    return best


def highlight_html(page_text: str, quote: str | None) -> tuple[str, bool]:
    """Return (html, found). The page text is escaped; only the <mark> is added."""
    span = locate_quote(page_text, quote) if quote else None
    if span:
        a, b = span
        body = (html.escape(page_text[:a]) + "<mark>" + html.escape(page_text[a:b]) + "</mark>"
                + html.escape(page_text[b:]))
    else:
        body = html.escape(page_text)
    return body.replace("\n", "<br>"), span is not None


def format_hours(hours: float) -> str:
    if hours < 0:
        return f"overdue by {abs(hours):.0f} h"
    days, rem = divmod(hours, 24)
    return f"{int(days)} d {rem:.0f} h left" if days else f"{rem:.0f} h left"
