"""Guardrails: what happens when the model gets it wrong.

The principle under test: a failure costs the nurse time, never a wrong
status. Failures become "unverified" or "AI failed" with the reason shown.
They never become not_met or missing.
"""

from src.llm import LLMError
from src.verify import rollup

from .conftest import element, rule


def _set(responses, element_id, **changes):
    for el in responses["check"]["elements"]:
        if el["element_id"] == element_id:
            el.update(changes)
    return responses


# ---------------------------------------------------------- fabricated quotes
def test_fabricated_quote_is_caught_and_routed_to_a_person(run, fixture_responses):
    _set(fixture_responses, "C2d", evidence=[{"page": 7, "quote": "Patient reports no relief after 12 weeks of therapy"}])
    result = run(fixture_responses)
    c2 = rule(result, "C2")
    assert not c2["verified"]
    assert "quote not found" in element(result, "C2d")["problems"][0]
    assert result["route"]["queue"] == "nurse_review_needs_verification"
    assert any("C2 could not be verified" in r for r in result["route"]["reasons"])


def test_fabricated_quote_does_not_change_the_status(run, fixture_responses):
    _set(fixture_responses, "C2d", evidence=[{"page": 7, "quote": "Patient reports no relief after 12 weeks of therapy"}])
    c2 = rule(run(fixture_responses), "C2")
    assert c2["status"] == "met"  # the AI's proposal is shown as-is, flagged unverified
    assert c2["status"] != "not_met"


def test_unverified_rule_never_suggests_approval(run, fixture_responses):
    # Make every rule met, but with one fabricated quote.
    _set(fixture_responses, "C3a", status="met", evidence=[{"page": 3, "quote": "No prior lumbar imaging has been performed"}])
    _set(fixture_responses, "C4a", status="met", evidence=[{"page": 5, "quote": "Order MRI lumbar spine without contrast"}])
    result = run(fixture_responses)
    assert "approve" not in result["route"]["suggested_actions"]


def test_met_without_any_quote_is_unverified(run, fixture_responses):
    _set(fixture_responses, "C1a", evidence=[])
    result = run(fixture_responses)
    assert not rule(result, "C1")["verified"]
    assert "no supporting quote" in element(result, "C1a")["problems"][0]


# ------------------------------------------------------ missing vs not met
def test_rollup_missing_never_becomes_not_met():
    assert rollup(["met", "missing", "met"]) == "missing"
    assert rollup(["missing"]) == "missing"
    assert rollup(["met", "missing", "not_met"]) == "not_met"  # explicit contrary evidence wins
    assert rollup(["met", "met"]) == "met"


def test_part_with_no_result_gives_no_rule_status():
    assert rollup(["met", None]) is None


def test_c4_with_no_evidence_stays_missing(run, fixture_responses):
    assert rule(run(fixture_responses), "C4")["status"] == "missing"


def test_model_skipping_a_part_is_unverified_not_missing(run, fixture_responses):
    fixture_responses["check"]["elements"] = [
        e for e in fixture_responses["check"]["elements"] if e["element_id"] != "C2b"]
    result = run(fixture_responses)
    c2 = rule(result, "C2")
    assert c2["status"] is None and not c2["verified"]
    assert "no result for this part" in element(result, "C2b")["problems"][0]


def test_duplicate_results_for_a_part_are_flagged(run, fixture_responses):
    els = fixture_responses["check"]["elements"]
    els.append(dict(next(e for e in els if e["element_id"] == "C3a"), status="met"))
    result = run(fixture_responses)
    assert not rule(result, "C3")["verified"]


# ------------------------------------------------------------ call failures
def test_schema_failure_goes_to_a_person_and_sets_no_status(run, fixture_responses):
    _set(fixture_responses, "C3a", status="denied")  # not an allowed value
    result = run(fixture_responses)
    assert result["rules"] is None
    assert result["route"]["queue"] == "nurse_review_ai_failed"
    assert "schema check" in result["call_failures"][0]
    assert any("Nothing was marked not met or missing" in r for r in result["route"]["reasons"])


def test_invalid_json_goes_to_a_person(run, fixture_responses):
    fixture_responses["check"] = "{not json"
    result = run(fixture_responses)
    assert result["rules"] is None and result["route"]["queue"] == "nurse_review_ai_failed"


def test_provider_outage_goes_to_a_person(run, fixture_responses):
    fixture_responses["check"] = LLMError("Gemini call 'check' failed after 5 attempt(s): HTTP 503")
    fixture_responses["extract"] = LLMError("Gemini call 'extract' failed after 5 attempt(s): HTTP 503")
    result = run(fixture_responses)
    assert result["rules"] is None and result["extraction"] is None
    assert result["route"]["queue"] == "nurse_review_ai_failed"
    assert result["route"]["suggested_actions"] == []


def test_extraction_failure_keeps_rule_results_but_flags_the_case(run, fixture_responses):
    fixture_responses["extract"] = LLMError("timeout")
    result = run(fixture_responses)
    assert rule(result, "C3")["status"] == "not_met"
    assert result["route"]["queue"] == "nurse_review_needs_verification"
    assert any("extract" in r for r in result["route"]["reasons"])


def test_fabricated_extraction_quote_is_flagged(run, fixture_responses):
    fixture_responses["extract"]["diagnosis"][0]["quote"] = "Lumbar spinal stenosis with neurogenic claudication"
    ex = run(fixture_responses)["extraction"]
    assert not ex["diagnosis"]["verified"]
    assert ex["requested_service"]["verified"]
