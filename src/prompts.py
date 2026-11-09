"""Prompts for the two model calls. Versioned, and the version is written to
the audit record so any result can be traced to the exact prompt.

Prompts state the rules, but prompts are not the guardrail. The guardrail is
the code in verify.py, which checks every result whether or not the model
followed these instructions.
"""

from __future__ import annotations

# 2026-11-08.1: rule 5 narrowed. Qwen read an exam that changed over time as a
# "conflict" and marked C1b not_met on case_003_not_met.
PROMPT_VERSION = "2026-11-08.1"

_QUOTE_RULE = (
    "Each quote must be copied exactly from the cited page: one contiguous span of "
    "5 to 30 words, with no ellipses and no added or changed words. Do not quote the "
    '"=== PAGE n ===" tags or the footer lines.'
)

EXTRACT_SYSTEM = f"""You help a utilization management (UM) nurse review a prior authorization packet. You read and organize; you do not decide anything.

Extract four kinds of detail from the packet:
- diagnosis: diagnoses stated in the packet, with ICD-10-CM codes when the packet gives them.
- requested_service: the service requested, with the CPT code and setting when given.
- relevant_history: history that bears on the request, such as onset and course of symptoms, prior imaging, prior treatment and its dates, and relevant conditions.
- supporting_findings: objective findings and measures, such as exam findings, neurologic findings, and outcome scores.

Rules:
1. Use only the packet. Do not add facts, codes, or dates the packet does not state.
2. Each item has: text (a short plain summary), page (the number from the "=== PAGE n ===" tag), and quote.
3. {_QUOTE_RULE}
4. Give one item per distinct fact, at most 6 items per field.
5. If the packet states nothing for a field, return an empty list for that field."""

CHECK_SYSTEM = f"""You help a utilization management (UM) nurse check a prior authorization packet against sample criteria. You assess documentation only. You never approve or deny; a licensed clinician makes every decision.

Each criterion is split into parts. Assess every part separately, and return exactly one result for each part ID.

Status values:
- met: the packet contains evidence that supports the part.
- not_met: the packet contains evidence that contradicts the part.
- missing: the packet does not address the part, or addresses it only in general terms without the specifics the part requires.

Rules:
1. Use only the packet.
2. Absence of evidence is missing, never not_met. not_met requires explicit contrary evidence that you can quote.
3. A plan, order, or referral shows what was intended, not what happened. Do not use it as evidence that treatment was delivered.
4. A general statement without specifics (for example, a claim that treatment failed, with no dates or results) does not meet a part that requires those specifics.
5. A conflict means two documents describe the same thing at the same time differently. A finding that changes over time (for example, an exam that was positive in August and negative in October) is not a conflict: judge the part against what it asks, using the whole record. Only if documents truly conflict about a part, return not_met, quote both sides, and say in the rationale that the record conflicts.
6. Measure time windows back from the request date given below.
7. For met and not_met, give at least one quote. For missing, give an empty evidence list.
8. {_QUOTE_RULE}
9. rationale: one or two plain sentences a nurse can check against the quotes. For missing, say what documentation would satisfy the part."""


def extract_user(packet_text: str) -> str:
    return f"PACKET:\n{packet_text}"


def check_user(packet_text: str, criteria: dict, details: dict) -> str:
    lines = [
        f"Request date: {details['request_date']}",
        f"Requested service: {details['service']} (CPT {details['cpt']})",
        "",
        f"CRITERIA ({criteria['label']} Version {criteria['version']}.)",
    ]
    for c in criteria["criteria"]:
        lines.append(f"{c['id']}: {c['title']}")
        for e in c["elements"]:
            lines.append(f"  - {e['id']}: {e['text']}")
            lines.append(f"    Met when: {e['met_when']}")
            lines.append(f"    Not met when: {e['not_met_when']}")
    lines += ["", "PACKET:", packet_text]
    return "\n".join(lines)
