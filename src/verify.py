"""Code checks on model output. These, not prompt instructions, are the guardrail.

1. Every quote must appear on the page it cites (after normalization).
2. Every part of every rule must have exactly one result.
3. A met or not_met part must have at least one quote.
4. Rule status is computed here from part statuses. The model never sets it.
5. Anything that fails is marked unverified and goes to a person. A failure
   never turns into not_met or missing.

Limit to say out loud: a verified quote proves the text exists on that page.
It does not prove the text supports the status. That is the nurse's job,
which is why the nurse confirms or overrides every rule.
"""

from __future__ import annotations

import re
import unicodedata

from .schemas import EXTRACTION_FIELDS

_QUOTE_CHARS = "\"'`"
_DASHES = {"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"}
_CURLY = {"“": '"', "”": '"', "‘": "'", "’": "'"}

MIN_QUOTE_CHARS = 12  # stops trivially short "quotes" like "yes" or "PT" from passing


def normalize(text: str) -> str:
    """Normalize text before comparing a quote with a page.

    Lessons from the benchmark: models wrap quotes in quotation marks, and PDF
    text wraps lines mid-sentence. So: unify unicode, dashes, and curly quotes,
    collapse all whitespace (including line breaks), trim surrounding quotation
    marks and trailing punctuation, and compare case-insensitively.

    It does NOT forgive changed words. A paraphrase fails, by design.
    """
    text = unicodedata.normalize("NFKC", text)
    for bad, good in {**_DASHES, **_CURLY}.items():
        text = text.replace(bad, good)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip(_QUOTE_CHARS + " ")
    text = text.rstrip(".,;: ")
    return text.lower()


def quote_on_page(quote: str, page_text: str) -> tuple[bool, str]:
    """Return (ok, reason). ok is True only if the normalized quote is a
    substring of the normalized page text."""
    q = normalize(quote)
    if len(q) < MIN_QUOTE_CHARS:
        return False, f"quote too short to verify ({len(q)} characters)"
    if "..." in q or "…" in q:
        return False, "quote contains an ellipsis, so it is not one exact span"
    if q in normalize(page_text):
        return True, "quote found on cited page"
    return False, "quote not found on cited page"


def locate_quote(page_text: str, quote: str) -> tuple[int, int] | None:
    """Find where a quote sits in the ORIGINAL page text, for highlighting.

    Uses the same normalization as quote_on_page, but keeps a map from each
    normalized character back to its position in the original text.
    Returns (start, end) indexes into page_text, or None if not found.
    """
    q = normalize(quote)
    if not q:
        return None
    chars: list[str] = []
    origin: list[int] = []
    prev_space = True
    for i, ch in enumerate(page_text):
        piece = unicodedata.normalize("NFKC", ch)
        for bad, good in {**_DASHES, **_CURLY}.items():
            piece = piece.replace(bad, good)
        for c in piece.lower():
            if c.isspace():
                if prev_space:
                    continue
                c = " "
                prev_space = True
            else:
                prev_space = False
            chars.append(c)
            origin.append(i)
    at = "".join(chars).find(q)
    if at < 0:
        return None
    return origin[at], origin[at + len(q) - 1] + 1


def check_citation(page: int, quote: str, pages: dict[int, str]) -> dict:
    if page not in pages:
        ok, reason = False, f"cited page {page} does not exist (packet has {len(pages)} pages)"
    else:
        ok, reason = quote_on_page(quote, pages[page])
    return {"page": page, "quote": quote, "verified": ok, "check": reason}


# ----------------------------------------------------------------- extraction
def verify_extraction(data: dict, pages: dict[int, str]) -> dict:
    fields = {}
    for name in EXTRACTION_FIELDS:
        items = []
        for item in data.get(name, []):
            c = check_citation(item["page"], item["quote"], pages)
            items.append({"text": item["text"], **c})
        fields[name] = {
            "items": items,
            "found": bool(items),
            "verified": all(i["verified"] for i in items),
        }
    return fields


# ---------------------------------------------------------------- rule check
def rollup(statuses: list[str | None]) -> str | None:
    """Rule status from part statuses. Computed in code, never by the model.

    any not_met -> not_met; else any missing -> missing; else met.
    If any part has no result at all, the rule has no status (None): a gap in
    the AI output is not evidence of anything.
    """
    if not statuses or any(s is None for s in statuses):
        return None
    if "not_met" in statuses:
        return "not_met"
    if "missing" in statuses:
        return "missing"
    return "met"


def verify_check(data: dict, pages: dict[int, str], criteria: dict) -> dict:
    by_id: dict[str, dict] = {}
    extra_problems: list[str] = []
    for el in data.get("elements", []):
        eid = el["element_id"]
        if eid in by_id:
            by_id[eid]["problems"].append("model returned more than one result for this part")
            continue
        evidence = [check_citation(ev["page"], ev["quote"], pages) for ev in el.get("evidence", [])]
        problems = [f"p.{e['page']}: {e['check']}" for e in evidence if not e["verified"]]
        if el["status"] in ("met", "not_met") and not evidence:
            problems.append(f"status '{el['status']}' has no supporting quote")
        by_id[eid] = {
            "element_id": eid,
            "status": el["status"],
            "rationale": el.get("rationale", ""),
            "evidence": evidence,
            "problems": problems,
        }

    rules = []
    for c in criteria["criteria"]:
        elements = []
        for spec in c["elements"]:
            el = by_id.pop(spec["id"], None)
            if el is None:
                el = {"element_id": spec["id"], "status": None, "rationale": "", "evidence": [],
                      "problems": ["model returned no result for this part"]}
            el["text"] = spec["text"]
            el["verified"] = not el["problems"]
            elements.append(el)
        rules.append({
            "id": c["id"],
            "title": c["title"],
            "status": rollup([e["status"] for e in elements]),
            "verified": all(e["verified"] for e in elements),
            "elements": elements,
        })
    for eid in by_id:  # cannot happen when the schema enum is enforced, but checked anyway
        extra_problems.append(f"model returned a result for unknown part '{eid}'")
    return {"rules": rules, "problems": extra_problems}
