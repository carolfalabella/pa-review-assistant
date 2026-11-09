"""The two model calls: Extract Clinical Details, and Check & Summary.

Both calls get the full page-tagged packet. They are independent (call 2 does
not read call 1's output), so an extraction mistake can't spill into the rule
check, and the two can run at the same time.

Each call's output is parsed and schema-checked here. Anything that isn't
valid JSON in the expected shape becomes a failed call with the reason
recorded. It never becomes a status.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import prompts
from .llm import LLMError, LLMResponse
from .schemas import check_schema, extraction_schema, validate


@dataclass
class CallResult:
    name: str
    ok: bool
    data: dict | None = None
    error: str | None = None
    raw_text: str | None = None
    response: LLMResponse | None = None
    schema_errors: list[str] = field(default_factory=list)

    attempts: int | None = None  # kept even when the call fails, so retries are counted
    waited_seconds: float | None = None

    def meta(self) -> dict:
        r = self.response
        return {
            "call": self.name,
            "ok": self.ok,
            "error": self.error,
            "provider": r.provider if r else None,
            "model": r.model if r else None,
            "seconds": r.seconds if r else None,
            "attempts": r.attempts if r else self.attempts,
            "waited_seconds": r.waited_seconds if r else self.waited_seconds,
            "usage": r.usage if r else None,
            "label": r.label if r else None,
        }


def call_json(provider, name: str, system: str, user: str, schema: dict) -> CallResult:
    try:
        resp = provider.generate_json(name, system, user, schema)
    except LLMError as exc:
        return CallResult(name, ok=False, error=str(exc), attempts=exc.attempts,
                          waited_seconds=exc.waited_seconds)
    try:
        data = json.loads(resp.text)
    except json.JSONDecodeError as exc:
        return CallResult(name, ok=False, error=f"Model output is not valid JSON ({exc.msg})",
                          raw_text=resp.text, response=resp)
    errors = validate(data, schema)
    if errors:
        shown = "; ".join(errors[:3]) + (f" (+{len(errors) - 3} more)" if len(errors) > 3 else "")
        return CallResult(name, ok=False, error=f"Model output failed the schema check: {shown}",
                          data=data, raw_text=resp.text, response=resp, schema_errors=errors)
    return CallResult(name, ok=True, data=data, raw_text=resp.text, response=resp)


def run_extraction(provider, packet_text: str) -> CallResult:
    return call_json(provider, "extract", prompts.EXTRACT_SYSTEM, prompts.extract_user(packet_text),
                     extraction_schema())


def run_check(provider, packet_text: str, criteria: dict, details: dict, element_ids: list[str]) -> CallResult:
    return call_json(provider, "check", prompts.CHECK_SYSTEM,
                     prompts.check_user(packet_text, criteria, details), check_schema(element_ids))
