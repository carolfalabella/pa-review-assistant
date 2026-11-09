"""PDF to page-tagged text.

Demo stand-in for the production Parse step. Production adds OCR, a page
quality check, and routes low-quality pages to a person. This demo reads a
text-based PDF only, so no OCR runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass(frozen=True)
class Page:
    number: int  # 1-based, matches the page numbers a reviewer sees
    text: str


def _clean(text: str) -> str:
    # Keep line breaks for readability, but collapse runs of spaces.
    text = text.replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def read_pages(pdf_path: str | Path) -> list[Page]:
    reader = PdfReader(str(pdf_path))
    pages = [Page(i + 1, _clean(pg.extract_text() or "")) for i, pg in enumerate(reader.pages)]
    empty = [pg.number for pg in pages if not pg.text]
    if empty:
        # A text-less page would need OCR. Fail loudly instead of silently
        # sending the model a packet with holes in it.
        raise ValueError(f"No extractable text on page(s) {empty}; OCR is out of demo scope.")
    return pages


def to_prompt_text(pages: list[Page]) -> str:
    """Tag every page so the model can cite page numbers."""
    return "\n\n".join(f"=== PAGE {pg.number} ===\n{pg.text}" for pg in pages)
