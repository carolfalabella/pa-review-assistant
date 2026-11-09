"""Output schemas for the two model calls, plus a small validator.

Design choice to defend: the status field is an enum of exactly three values.
There is no "deny", "denied", or "partial" value anywhere, so the AI cannot
express a denial even if a prompt is ignored. "AI never denies" is a property
of the code, not a promise in a prompt.

The validator is hand-written (about 50 lines) instead of using the
jsonschema package, so it has no compiled dependencies and runs on any
Python version. It supports only the keywords these schemas use.
"""

from __future__ import annotations

from typing import Any

STATUSES = ("met", "not_met", "missing")

EXTRACTION_FIELDS = ("diagnosis", "requested_service", "relevant_history", "supporting_findings")

_CITATION = {
    "type": "object",
    "properties": {
        "page": {"type": "integer", "minimum": 1},
        "quote": {"type": "string"},
    },
    "required": ["page", "quote"],
}


def extraction_schema() -> dict:
    item = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "page": {"type": "integer", "minimum": 1},
            "quote": {"type": "string"},
        },
        "required": ["text", "page", "quote"],
    }
    return {
        "type": "object",
        "properties": {f: {"type": "array", "items": item} for f in EXTRACTION_FIELDS},
        "required": list(EXTRACTION_FIELDS),
    }


def check_schema(element_ids: list[str]) -> dict:
    # Property order matters for generation: the model writes its evidence
    # and rationale BEFORE it commits to a status.
    element = {
        "type": "object",
        "properties": {
            "element_id": {"type": "string", "enum": list(element_ids)},
            "evidence": {"type": "array", "items": _CITATION},
            "rationale": {"type": "string"},
            "status": {"type": "string", "enum": list(STATUSES)},
        },
        "required": ["element_id", "evidence", "rationale", "status"],
    }
    return {
        "type": "object",
        "properties": {"elements": {"type": "array", "items": element}},
        "required": ["elements"],
    }


_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


def validate(instance: Any, schema: dict, path: str = "$") -> list[str]:
    """Return a list of problems. An empty list means valid."""
    errors: list[str] = []
    expected = schema.get("type")
    if expected:
        py_type = _TYPES[expected]
        is_bool = isinstance(instance, bool)
        if not isinstance(instance, py_type) or (is_bool and expected in ("integer", "number")):
            return [f"{path}: expected {expected}, got {type(instance).__name__}"]
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value {instance!r} is not one of {schema['enum']}")
    if "minimum" in schema and isinstance(instance, (int, float)) and instance < schema["minimum"]:
        errors.append(f"{path}: {instance} is below the minimum {schema['minimum']}")
    if expected == "object":
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required field '{key}'")
        for key, sub in schema.get("properties", {}).items():
            if key in instance:
                errors.extend(validate(instance[key], sub, f"{path}.{key}"))
    if expected == "array" and "items" in schema:
        for i, item in enumerate(instance):
            errors.extend(validate(item, schema["items"], f"{path}[{i}]"))
    return errors
