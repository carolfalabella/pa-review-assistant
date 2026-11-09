"""Golden case: the demo packet with known-good responses gives C1-C4 as designed.

The responses are a hand-written fixture, not model output. This tests the
code around the model. Model quality is measured by scripts/eval_cases.py.
"""

from src.llm import SavedProvider
from src.pipeline import run_case

from .conftest import DATA, FIXTURE, rule


def test_rule_results_match_design(run, fixture_responses):
    result = run(fixture_responses)
    assert {r["id"]: r["status"] for r in result["rules"]} == {
        "C1": "met", "C2": "met", "C3": "not_met", "C4": "missing"}
    assert all(r["verified"] for r in result["rules"])


def test_c2_evidence_comes_from_the_pt_summary(run, fixture_responses):
    pages = {ev["page"] for e in rule(run(fixture_responses), "C2")["elements"] for ev in e["evidence"]}
    assert pages <= {6, 7}


def test_all_four_extraction_fields_found_and_verified(run, fixture_responses):
    ex = run(fixture_responses)["extraction"]
    assert set(ex) == {"diagnosis", "requested_service", "relevant_history", "supporting_findings"}
    assert all(f["found"] and f["verified"] for f in ex.values())


def test_route_suggests_referral_and_information_request_not_approval(run, fixture_responses):
    r = run(fixture_responses)["route"]
    assert r["queue"] == "nurse_review"
    assert r["suggested_actions"] == ["refer_to_medical_director", "request_information"]


def test_deadline_is_seven_calendar_days_for_ma_standard(run, fixture_responses):
    dl = run(fixture_responses)["deadline"]
    assert dl["limit"] == "7 calendar days"
    assert dl["due_at"].startswith("2026-11-09T09:00")


def test_saved_provider_replays_and_is_labeled(settings):
    result = run_case(DATA / "case_001.pdf", settings, provider=SavedProvider(FIXTURE))
    assert "Not a live model call" in result["saved_run_label"]
    assert result["rules"][2]["status"] == "not_met"


def test_saved_run_for_a_different_packet_is_refused(settings):
    result = run_case(DATA / "case_002_missing.pdf", settings, provider=SavedProvider(FIXTURE))
    assert result["rules"] is None
    assert result["route"]["queue"] == "nurse_review_ai_failed"
    assert "different packet" in " ".join(result["call_failures"])


def test_saved_run_label_always_starts_with_saved_run(settings):
    # Regression (Nov 9): a saved file with its own label must still be shown as a SAVED RUN.
    result = run_case(DATA / "case_001.pdf", settings, provider=SavedProvider(FIXTURE))
    assert result["saved_run_label"].startswith("SAVED RUN (HAND-WRITTEN TEST FIXTURE")
