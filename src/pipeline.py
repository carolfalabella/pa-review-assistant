"""Runs the demo pipeline end to end for one packet.

Ingest -> Parse -> (stand-in) Read Details & Match -> Rule Selection
  -> [Extract Clinical Details  ||  Check & Summary]   (two model calls, in parallel)
  -> code checks -> Route & Deadline -> audit record

Command line:
  python -m src.pipeline data/synthetic/case_001.pdf
  python -m src.pipeline data/synthetic/case_001.pdf --provider ollama --save
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import prompts
from .audit import AuditLog
from .calls import CallResult, run_check, run_extraction
from .config import Settings, load_settings
from .criteria import criteria_version, element_ids, load_criteria
from .ingest import read_pages, to_prompt_text
from .intake import case_details
from .llm import LLMError, SavedProvider, WaitCallback, make_provider
from .route import deadline, route
from .verify import verify_check, verify_extraction


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_case(pdf_path: str | Path, settings: Settings | None = None, provider=None,
             audit: AuditLog | None = None, on_wait: WaitCallback | None = None) -> dict:
    settings = settings or load_settings()
    pdf_path = Path(pdf_path)
    case_id = pdf_path.stem
    run_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    started = time.monotonic()

    pages_list = read_pages(pdf_path)
    pages = {p.number: p.text for p in pages_list}
    packet_text = to_prompt_text(pages_list)
    packet_sha = sha256_file(pdf_path)
    details = case_details(case_id, settings.receipt_time)
    criteria = load_criteria()
    ids = element_ids(criteria)

    call_failures: list[str] = []
    extraction = check = None
    extract_call = check_call = None
    label = None
    try:
        provider = provider or make_provider(settings, on_wait=on_wait)
        if isinstance(provider, SavedProvider):
            label = provider.label
            if provider.packet_sha256 and provider.packet_sha256 != packet_sha:
                raise LLMError("Saved run was recorded on a different packet; refusing to replay it.")
    except LLMError as exc:
        call_failures.append(str(exc))

    if not call_failures:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_extract = pool.submit(run_extraction, provider, packet_text)
            f_check = pool.submit(run_check, provider, packet_text, criteria, details, ids)
            extract_call, check_call = f_extract.result(), f_check.result()
        for call in (extract_call, check_call):
            if not call.ok:
                call_failures.append(f"{call.name}: {call.error}")
        if extract_call.ok:
            extraction = verify_extraction(extract_call.data, pages)
        if check_call.ok:
            check = verify_check(check_call.data, pages, criteria)

    rules = check["rules"] if check else None
    routing = route(call_failures, rules, check["problems"] if check else [])

    calls = [c for c in (extract_call, check_call) if c]
    first = next((c.response for c in calls if c.response), None)
    result = {
        "run_id": run_id,
        "case_id": case_id,
        "packet": str(pdf_path),
        "packet_sha256": packet_sha,
        "page_count": len(pages),
        "pages": pages,
        "details": details,
        "deadline": deadline(details),
        "provider": first.provider if first else settings.provider,
        "model": first.model if first else (settings.gemini_model if settings.provider == "gemini"
                                             else settings.ollama_model),
        "saved_run_label": label,
        "prompt_version": prompts.PROMPT_VERSION,
        "criteria_version": criteria_version(criteria),
        "criteria_label": criteria["label"],
        "extraction": extraction,
        "rules": rules,
        "route": routing,
        "call_failures": call_failures,
        "calls": [c.meta() for c in calls],
        "raw": {c.name: c.raw_text for c in calls},
        "seconds": round(time.monotonic() - started, 1),
    }
    if audit:
        audit.append("pipeline_run", {k: v for k, v in result.items() if k != "pages"})
    return result


def save_run(result: dict, out_dir: Path) -> Path:
    """Save raw model responses so the run can be replayed with PROVIDER=saved."""
    if result["provider"] == "saved":
        raise ValueError("This run is already a replay; save the original run instead.")
    if not result["raw"].get("extract") or not result["raw"].get("check"):
        raise ValueError("Can only save a run where both model calls returned output.")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result['case_id']}__{result['provider']}__{result['run_id']}.json"
    record = {
        "label": "SAVED RUN",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "case_id": result["case_id"],
        "packet_sha256": result["packet_sha256"],
        "prompt_version": result["prompt_version"],
        "criteria_version": result["criteria_version"],
        "source": {"provider": result["provider"], "model": result["model"], "run_id": result["run_id"]},
        "responses": {"extract": result["raw"]["extract"], "check": result["raw"]["check"]},
    }
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def summarize(result: dict) -> str:
    lines = [
        f"Run {result['run_id']}  case {result['case_id']}  {result['provider']}/{result['model']}  "
        f"{result['seconds']}s",
    ]
    if result["saved_run_label"]:
        lines.append(f"*** {result['saved_run_label']} ***")
    for c in result["calls"]:
        timing = f" ({c['seconds']}s" if c["seconds"] is not None else ""
        if timing and c.get("waited_seconds"):
            timing += f", incl. {c['waited_seconds']}s retry waits over {c['attempts']} attempts"
        timing += ")" if timing else ""
        lines.append(f"  call {c['call']}: {'ok' if c['ok'] else 'FAILED'}{timing}"
                     + (f" -> {c['error']}" if c["error"] else ""))
    if result["extraction"]:
        for name, f in result["extraction"].items():
            mark = "verified" if f["verified"] else "UNVERIFIED"
            first = f["items"][0]["text"] if f["items"] else "(none found)"
            lines.append(f"  {name:20} {mark:10} {first}")
    if result["rules"]:
        for r in result["rules"]:
            mark = "verified" if r["verified"] else "UNVERIFIED"
            parts = ", ".join(f"{e['element_id']}={e['status']}" for e in r["elements"])
            lines.append(f"  {r['id']}  {str(r['status']):8} {mark:10} [{parts}]")
            for e in r["elements"]:
                for p in e["problems"]:
                    lines.append(f"       ! {e['element_id']}: {p}")
    lines.append(f"  route: {result['route']['queue']}  suggested: {result['route']['suggested_actions']}")
    for reason in result["route"]["reasons"]:
        lines.append(f"    - {reason}")
    dl = result["deadline"]
    if dl.get("configured"):
        lines.append(f"  deadline: due {dl['due_at']} ({dl['limit']}), {dl['remaining_hours']} h left")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the PA review pipeline on one synthetic packet.")
    ap.add_argument("pdf")
    ap.add_argument("--provider", choices=["gemini", "ollama", "saved"])
    ap.add_argument("--saved-run", help="saved-run file for --provider saved")
    ap.add_argument("--save", action="store_true", help="save raw responses for replay")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = ap.parse_args(argv)

    settings = load_settings()
    if args.provider:
        settings = settings.with_(provider=args.provider)
    if args.saved_run:
        settings = settings.with_(saved_run=Path(args.saved_run))

    def on_wait(call, attempt, wait, reason):
        print(f"  [{call}] busy ({reason}); retrying in {wait}s (attempt {attempt})", file=sys.stderr)

    audit = AuditLog(settings.runs_dir / "audit.jsonl")
    result = run_case(args.pdf, settings, audit=audit, on_wait=on_wait)
    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "pages"}, indent=2, ensure_ascii=False))
    else:
        print(summarize(result))
    if args.save:
        print(f"Saved: {save_run(result, settings.runs_dir / 'saved')}")
    return 0 if not result["call_failures"] else 1


if __name__ == "__main__":
    sys.exit(main())
