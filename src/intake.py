"""Read Details and Match & Label, demo stand-ins.

Production: read member, provider, urgency, and service from the request (AI
for fax and PDF, code for 278 and FHIR), match them against the plan's core
system, and start the clock from the channel's own receipt time.

Demo: every synthetic packet belongs to the same fixed, synthetic Medicare
Advantage member and standard request. Receipt time is the moment the packet
is loaded, unless DEMO_RECEIPT_TIME is set.
"""

from __future__ import annotations

from datetime import datetime

FIXED_DETAILS = {
    "member_id": "SYN-MA-0001234",
    "member_name": "Alex Q. Sample (synthetic)",
    "line_of_business": "medicare_advantage",
    "urgency": "standard",
    "request_date": "2026-11-02",
    "service": "MRI lumbar spine without contrast",
    "cpt": "72148",
    "diagnosis_code": "M54.16",
    "provider": "Morgan Ellis, MD (synthetic)",
    "state": "XX (synthetic)",
}


def case_details(case_id: str, receipt_time: str | None = None) -> dict:
    details = dict(FIXED_DETAILS, case_id=case_id)
    received = datetime.fromisoformat(receipt_time) if receipt_time else datetime.now().astimezone()
    if received.tzinfo is None:
        received = received.astimezone()
    details["received_at"] = received.isoformat(timespec="seconds")
    return details
