"""Audit record: one JSON line per event, hash-chained so edits are detectable.

Each record stores the hash of the record before it. Changing or deleting any
line breaks the chain, and verify_chain() reports where.

Recorded per run: run ID, case, packet hash, provider, model, prompt version,
criteria version, timings and retries, raw model output, verification
results, and route. Recorded per reviewer action: who, role, what, the AI's
status, the final status, and the reason.

Demo vs production: this demo logs synthetic text. Production keeps PHI out of
logs and telemetry (metadata only), stores the audit trail in a protected
store, and feeds the plan's security monitoring.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

GENESIS = "0" * 64


def _hash(record: dict) -> str:
    body = json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


class AuditLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last(self) -> tuple[int, str]:
        if not self.path.exists():
            return 0, GENESIS
        last = None
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = json.loads(line)
        return (last["seq"], last["hash"]) if last else (0, GENESIS)

    def append(self, event: str, payload: dict, actor: str = "system", role: str = "system") -> dict:
        seq, prev = self._last()
        record = {
            "seq": seq + 1,
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "event": event,
            "actor": actor,
            "role": role,
            "payload": payload,
            "prev_hash": prev,
        }
        record["hash"] = _hash(record)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def records(self, run_id: str | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as f:
            out = [json.loads(line) for line in f if line.strip()]
        if run_id:
            out = [r for r in out if r["payload"].get("run_id") == run_id]
        return out


def verify_chain(path: Path) -> tuple[bool, list[str]]:
    problems = []
    prev = GENESIS
    if not Path(path).exists():
        return True, []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, start=1):
            if not line.strip():
                continue
            rec = json.loads(line)
            stored = rec.pop("hash", None)
            if rec.get("prev_hash") != prev:
                problems.append(f"line {n}: does not follow the previous record (deleted or reordered)")
            if _hash(rec) != stored:
                problems.append(f"line {n}: contents changed after it was written")
            prev = stored
    return not problems, problems
