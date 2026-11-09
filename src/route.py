"""Route & Deadline alert. Fixed rules in code; no model involved.

Regulated routing must be testable and repeatable, so it lives in a decision
table, not in a prompt. Every case goes to a person. There is no route to a
denial or partial approval, and no automatic approval in this demo.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# Example deadline table. In production, Compliance owns this table.
DEADLINES = {
    ("medicare_advantage", "standard"): timedelta(days=7),
    ("medicare_advantage", "urgent"): timedelta(hours=72),
    ("medicaid", "standard"): timedelta(days=7),
    ("medicaid", "urgent"): timedelta(hours=72),
}
# Example alert thresholds, measured from receipt. The plan would set these.
ALERTS = {
    "standard": [(timedelta(days=5), "nurse"), (timedelta(days=6), "supervisor")],
    "urgent": [(timedelta(hours=48), "nurse"), (timedelta(hours=60), "supervisor")],
}


def deadline(details: dict, now: datetime | None = None) -> dict:
    key = (details["line_of_business"], details["urgency"])
    if key not in DEADLINES:
        return {"configured": False,
                "problem": f"No deadline rule for {key[0]} / {key[1]}; a person must set the clock."}
    received = datetime.fromisoformat(details["received_at"])
    now = now or datetime.now(received.tzinfo)
    due = received + DEADLINES[key]
    elapsed = now - received
    alert = None
    for threshold, who in ALERTS[details["urgency"]]:
        if elapsed >= threshold:
            alert = who
    remaining = due - now
    return {
        "configured": True,
        "received_at": received.isoformat(timespec="minutes"),
        "due_at": due.isoformat(timespec="minutes"),
        "limit": "7 calendar days" if DEADLINES[key] == timedelta(days=7) else "72 hours",
        "remaining_hours": round(remaining.total_seconds() / 3600, 1),
        "overdue": remaining.total_seconds() < 0,
        "alert": alert,  # None, "nurse", or "supervisor"
    }


def route(call_failures: list[str], rules: list[dict] | None, check_problems: list[str]) -> dict:
    """Return the queue, the reasons a nurse sees, and suggested next steps.

    Suggestions are only ever drawn from the three allowed case actions.
    """
    reasons: list[str] = []
    suggested: list[str] = []

    failures = [f"AI step failed: {f}" for f in call_failures]
    if rules is None:
        reasons += failures or ["AI rule check produced no results"]
        reasons.append("Review the packet directly. Nothing was marked not met or missing because of this failure.")
        return {"queue": "nurse_review_ai_failed", "reasons": reasons, "suggested_actions": suggested}

    # The rule check worked, but another step (extraction) may have failed.
    reasons += failures
    reasons += [f"AI check: {p}" for p in check_problems]
    unverified = [r for r in rules if not r["verified"]]
    not_met = [r for r in rules if r["status"] == "not_met" and r["verified"]]
    missing = [r for r in rules if r["status"] == "missing" and r["verified"]]

    for r in unverified:
        reasons.append(f"{r['id']} could not be verified; check the source before relying on it.")
    for r in not_met:
        reasons.append(f"{r['id']} not met: the record contains contrary evidence. Needs clinical judgment.")
    for r in missing:
        reasons.append(f"{r['id']} missing: the record does not address it.")

    if not_met:
        suggested.append("refer_to_medical_director")
    if missing:
        suggested.append("request_information")
    if not (unverified or not_met or missing):
        reasons.append("All rules met with verified citations. A nurse confirms before approval.")
        suggested.append("approve")

    queue = "nurse_review_needs_verification" if (unverified or check_problems or failures) else "nurse_review"
    return {"queue": queue, "reasons": reasons, "suggested_actions": suggested}
