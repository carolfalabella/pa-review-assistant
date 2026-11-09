"""Evaluate a provider on the three synthetic packets against their expected results.

  python -m scripts.eval_cases                       # PROVIDER from .env, all cases, 1 run each
  python -m scripts.eval_cases --provider ollama --repeats 3
  python -m scripts.eval_cases --cases case_001 --save   # also save a replayable run

Scoring (see each *_expected.json):
- rule status must match exactly
- part status must match, or be listed in also_accept
- every met / not_met part must have verified quotes
- for case_001, each extraction field must be found, verified, and mention the expected terms
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from src.audit import AuditLog
from src.config import ROOT, load_settings
from src.pipeline import run_case, save_run

CASES = ["case_001", "case_002_missing", "case_003_not_met"]
DATA = ROOT / "data" / "synthetic"


def score(result: dict, expected: dict) -> dict:
    checks = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    add("both model calls succeeded", not result["call_failures"], "; ".join(result["call_failures"]))
    rules = {r["id"]: r for r in (result["rules"] or [])}
    for cid, exp in expected["criteria"].items():
        r = rules.get(cid)
        add(f"{cid} rule status", r and r["status"] == exp["status"],
            f"expected {exp['status']}, got {r['status'] if r else 'no result'}")
        if not r:
            continue
        els = {e["element_id"]: e for e in r["elements"]}
        for eid, e_exp in exp["elements"].items():
            got = els[eid]
            allowed = [e_exp["status"], *e_exp.get("also_accept", [])]
            add(f"{eid} part status", got["status"] in allowed, f"expected {'/'.join(allowed)}, got {got['status']}")
            if got["status"] in ("met", "not_met"):
                add(f"{eid} quotes verified", got["verified"], "; ".join(got["problems"]))

    if "extraction" in expected and result["extraction"]:
        for field, f_exp in expected["extraction"].items():
            f = result["extraction"][field]
            text = " ".join(i["text"] + " " + i["quote"] for i in f["items"]).lower()
            missing_terms = [t for t in f_exp["must_mention"] if t.lower() not in text]
            add(f"extraction {field}", f["found"] and f["verified"] and not missing_terms,
                f"found={f['found']} verified={f['verified']} missing terms={missing_terms}")
    elif "extraction" in expected:
        add("extraction", False, "no extraction result")

    passed = sum(c["ok"] for c in checks)
    return {"passed": passed, "total": len(checks), "all_ok": passed == len(checks), "checks": checks}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["gemini", "ollama", "saved"])
    ap.add_argument("--cases", nargs="*", default=CASES)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--save", action="store_true", help="save each fully passing run for replay")
    ap.add_argument("--pause", type=float, default=0,
                    help="seconds to wait between runs (use ~30 on a free tier to stay under per-minute limits)")
    args = ap.parse_args(argv)

    settings = load_settings()
    if args.provider:
        settings = settings.with_(provider=args.provider)
    audit = AuditLog(settings.runs_dir / "audit.jsonl")

    def on_wait(call, attempt, wait, reason):
        print(f"    [{call}] busy ({reason}); retrying in {wait}s", file=sys.stderr)

    report = {"started": datetime.now().astimezone().isoformat(timespec="seconds"),
              "provider": settings.provider, "runs": []}
    first = True
    for case in args.cases:
        expected = json.loads((DATA / f"{case}_expected.json").read_text(encoding="utf-8"))
        for i in range(args.repeats):
            if args.pause and not first:
                print(f"  (pausing {args.pause:g}s)", flush=True)
                time.sleep(args.pause)
            first = False
            print(f"{case} run {i + 1}/{args.repeats} ...", flush=True)
            result = run_case(DATA / f"{case}.pdf", settings, audit=audit, on_wait=on_wait)
            s = score(result, expected)
            # The two calls run in parallel, so report each call's waits separately;
            # adding them together would overstate the delay.
            waits = {c["call"]: (c.get("waited_seconds") or 0) for c in result["calls"]}
            waited = max(waits.values(), default=0)
            busy = sum(max((c.get("attempts") or 1) - 1, 0) for c in result["calls"])
            wait_text = ", ".join(f"{k} {v:g}s" for k, v in waits.items() if v) or "none"
            print(f"  {s['passed']}/{s['total']} checks  {result['model']}  {result['seconds']}s wall time"
                  f"  (busy responses: {busy}; retry waits: {wait_text})")
            for c in s["checks"]:
                if not c["ok"]:
                    print(f"    FAIL {c['check']}: {c['detail']}")
            saved = None
            if args.save and s["all_ok"] and settings.provider != "saved":
                saved = str(save_run(result, settings.runs_dir / "saved"))
                print(f"  saved: {saved}")
            report["runs"].append({"case": case, "run": i + 1, "run_id": result["run_id"],
                                   "model": result["model"], "seconds": result["seconds"],
                                   "longest_call_wait_seconds": waited, "call_waits": waits,
                                   "busy_responses": busy, "score": s, "saved": saved,
                                   "rules": {r["id"]: r["status"] for r in (result["rules"] or [])}})

    out = settings.runs_dir / "eval" / f"eval_{settings.provider}_{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    ok = sum(r["score"]["all_ok"] for r in report["runs"])
    times = sorted(r["seconds"] for r in report["runs"])
    busy = sum(r["busy_responses"] for r in report["runs"])
    print(f"\n{ok}/{len(report['runs'])} runs fully correct. Wall time: fastest {times[0]}s, "
          f"slowest {times[-1]}s. Busy responses: {busy} across {len(report['runs'])} runs.")
    print(f"Report: {out}")
    return 0 if ok == len(report["runs"]) else 1


if __name__ == "__main__":
    sys.exit(main())
