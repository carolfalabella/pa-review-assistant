"""Audit chain integrity, and regression checks on the synthetic packets."""

import json

import pytest

from src.audit import AuditLog, verify_chain
from src.ingest import read_pages
from src.verify import quote_on_page

from .conftest import DATA


def test_audit_chain_verifies_and_detects_tampering(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append("pipeline_run", {"run_id": "r1", "rules": {"C3": "not_met"}})
    log.append("rule_review", {"run_id": "r1", "rule_id": "C3", "final_status": "not_met"}, actor="nurse-1", role="nurse")
    assert verify_chain(log.path) == (True, [])

    lines = log.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["payload"]["rules"]["C3"] = "met"
    log.path.write_text(json.dumps(tampered) + "\n" + lines[1] + "\n", encoding="utf-8")
    ok, problems = verify_chain(log.path)
    assert not ok and "changed" in problems[0]


def test_deleting_a_record_is_detected(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(3):
        log.append("e", {"i": i})
    lines = log.path.read_text(encoding="utf-8").splitlines()
    log.path.write_text(lines[0] + "\n" + lines[2] + "\n", encoding="utf-8")
    assert not verify_chain(log.path)[0]


def test_pipeline_writes_an_audit_record(settings, fixture_responses):
    from src.pipeline import run_case
    from .conftest import FakeProvider

    log = AuditLog(settings.runs_dir / "audit.jsonl")
    result = run_case(DATA / "case_001.pdf", settings, provider=FakeProvider(fixture_responses), audit=log)
    rec = log.records(result["run_id"])[0]
    for field in ("model", "provider", "prompt_version", "criteria_version", "packet_sha256", "raw", "rules", "route"):
        assert field in rec["payload"], field


@pytest.mark.parametrize("case", ["case_001", "case_002_missing", "case_003_not_met"])
def test_every_expected_quote_is_on_its_page(case):
    pages = {p.number: p.text for p in read_pages(DATA / f"{case}.pdf")}
    exp = json.loads((DATA / f"{case}_expected.json").read_text(encoding="utf-8"))
    anchors = [a for f in exp.get("extraction", {}).values() for a in f["anchors"]]
    anchors += [a for c in exp["criteria"].values() for e in c["elements"].values() for a in e["anchors"]]
    for a in anchors:
        assert quote_on_page(a["quote"], pages[a["page"]])[0], (case, a)


def test_variant_b_has_no_pt_dates_or_visit_count():
    pages = {p.number: p.text for p in read_pages(DATA / "case_002_missing.pdf")}
    pt = pages[6] + pages[7]
    assert "/2026" not in pt and "Total visits" not in pt
