"""Reviewer workbench rules. Pure functions, so the Streamlit app and the tests
use the same logic.

Assumed procedure (a plan would configure its own):
- The nurse confirms or overrides every rule. An override needs a reason.
  Confirming a result that failed verification also needs a reason, because
  the nurse is vouching for it after reading the source.
- Case actions are Approve, Request information, and Refer to medical director.
  There is no deny and no partial approval: a nurse cannot issue either here,
  and only a licensed reviewer makes an adverse determination.
- Approve is blocked until every rule is reviewed and every rule's status,
  after the nurse's review, is met.
"""

from __future__ import annotations

from datetime import datetime

from .schemas import STATUSES

RULE_ACTIONS = ("confirm", "override")
CASE_ACTIONS = ("approve", "request_information", "refer_to_medical_director")
CASE_ACTION_LABELS = {
    "approve": "Approve",
    "request_information": "Request information",
    "refer_to_medical_director": "Refer to medical director",
}


class ReviewError(ValueError):
    """The requested reviewer action is not allowed. The message says why."""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def review_from_status(rule: dict, final_status: str, reason: str = "", previous: dict | None = None,
                       actor: str = "demo-nurse") -> dict:
    """What the app calls. The nurse picks ONE thing, the final status, so the form can't
    hold two answers that disagree. Same as the AI status means confirm; a different
    status means override, which needs a reason."""
    if final_status not in STATUSES:
        raise ReviewError(f"Choose one of {STATUSES}")
    if final_status == rule["status"]:
        return review_rule(rule, "confirm", reason, actor=actor, previous=previous)
    return review_rule(rule, "override", reason, final_status, actor=actor, previous=previous)


def review_rule(rule: dict, action: str, reason: str = "", new_status: str | None = None,
                actor: str = "demo-nurse", previous: dict | None = None) -> dict:
    """Validate one reviewer action on one rule and return the review record.

    previous is the nurse's earlier review of this rule, if any. Changing a saved
    review to a different status needs a reason, even when switching back to the
    AI's status."""
    reason = (reason or "").strip()
    if action not in RULE_ACTIONS:
        raise ReviewError(f"Unknown rule action '{action}'")
    if action == "confirm":
        if rule["status"] is None:
            raise ReviewError(f"{rule['id']} has no AI status to confirm. Override it with a status and reason.")
        if not rule["verified"] and not reason:
            raise ReviewError(f"{rule['id']} failed verification. Give a reason to confirm it.")
        final = rule["status"]
    else:
        if new_status not in STATUSES:
            raise ReviewError(f"Override status must be one of {STATUSES}")
        if not reason:
            raise ReviewError(f"An override of {rule['id']} needs a reason.")
        final = new_status
    if previous and final != previous["final_status"] and not reason:
        raise ReviewError(f"Changing your saved review of {rule['id']} needs a reason.")
    return {
        "rule_id": rule["id"],
        "action": action,
        "ai_status": rule["status"],
        "ai_verified": rule["verified"],
        "final_status": final,
        "reason": reason,
        "actor": actor,
        "at": _now(),
    }


def approve_blockers(rules: list[dict], reviews: dict[str, dict]) -> list[str]:
    """Reasons Approve is disabled. An empty list means Approve is allowed."""
    if not rules:
        return ["There are no AI criteria results to review. Refer the case or request information instead."]
    blockers = []
    for r in rules:
        rev = reviews.get(r["id"])
        if rev is None:
            blockers.append(f"{r['id']} has not been reviewed")
        elif rev["final_status"] != "met":
            blockers.append(f"{r['id']} is {rev['final_status'].replace('_', ' ')} after review")
    return blockers


def case_action(rules: list[dict], reviews: dict[str, dict], action: str, note: str = "",
                actor: str = "demo-nurse") -> dict:
    note = (note or "").strip()
    if action not in CASE_ACTIONS:
        raise ReviewError(f"'{action}' is not an allowed case action. Allowed: {', '.join(CASE_ACTIONS)}")
    if action == "approve":
        blockers = approve_blockers(rules, reviews)
        if blockers:
            raise ReviewError("Approve is not available: " + "; ".join(blockers))
    if action == "refer_to_medical_director" and not note:
        raise ReviewError("A referral needs a reason for the medical director.")
    if action == "request_information" and not note:
        raise ReviewError("An information request needs the text to send.")
    return {"action": action, "note": note, "actor": actor, "at": _now(),
            "rule_reviews": [reviews[r["id"]] for r in rules if r["id"] in reviews]}


def draft_information_request(rules: list[dict], criteria: dict, details: dict,
                              reviews: dict[str, dict] | None = None) -> str:
    """Fixed template, not a model call. A person edits and approves it before it is sent."""
    reviews = reviews or {}
    texts = {e["id"]: e["text"] for c in criteria["criteria"] for e in c["elements"]}
    needed = []
    for r in rules:
        final = reviews.get(r["id"], {}).get("final_status", r["status"])
        if final != "missing":
            continue
        for e in r["elements"]:
            if e["status"] == "missing" or e["status"] is None:
                needed.append(f"- {texts[e['element_id']]}")
    if not needed:
        return ""
    return "\n".join([
        f"To: {details['provider']}",
        f"Re: Prior authorization request for {details['service']} (CPT {details['cpt']}), "
        f"member {details['member_id']}",
        "",
        "We are reviewing this request and need the following documentation to continue:",
        *needed,
        "",
        "Please send the documentation through the same channel as the original request.",
        "[Draft from a fixed template. A reviewer edits and approves it before it is sent.]",
    ])
