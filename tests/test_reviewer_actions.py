"""Reviewer workbench rules: required reasons and the Approve gate."""

import pytest

from src.criteria import load_criteria
from src.review import ReviewError, approve_blockers, case_action, draft_information_request, review_rule

from .conftest import rule


@pytest.fixture
def rules(run, fixture_responses):
    return run(fixture_responses)["rules"]


def _confirm_all(rules):
    return {r["id"]: review_rule(r, "confirm") for r in rules}


def test_approve_is_blocked_until_every_rule_is_reviewed(rules):
    assert len(approve_blockers(rules, {})) == 4


def test_approve_is_blocked_while_a_rule_is_not_met_or_missing(rules):
    blockers = approve_blockers(rules, _confirm_all(rules))
    assert blockers == ["C3 is not met after review", "C4 is missing after review"]
    with pytest.raises(ReviewError, match="Approve is not available"):
        case_action(rules, _confirm_all(rules), "approve")


def test_override_requires_a_reason(rules):
    c3 = next(r for r in rules if r["id"] == "C3")
    with pytest.raises(ReviewError, match="needs a reason"):
        review_rule(c3, "override", reason="  ", new_status="met")


def test_override_with_reason_can_unblock_approve(rules):
    reviews = _confirm_all(rules)
    by_id = {r["id"]: r for r in rules}
    reviews["C3"] = review_rule(by_id["C3"], "override", new_status="met",
                                reason="New radicular symptoms began after the June MRI; repeat imaging justified.")
    reviews["C4"] = review_rule(by_id["C4"], "override", new_status="met",
                                reason="Provider confirmed by phone that results decide on an epidural injection.")
    assert approve_blockers(rules, reviews) == []
    rec = case_action(rules, reviews, "approve")
    assert rec["action"] == "approve"
    assert rec["rule_reviews"][2]["ai_status"] == "not_met" and rec["rule_reviews"][2]["final_status"] == "met"


def test_confirming_an_unverified_result_requires_a_reason(run, fixture_responses):
    for el in fixture_responses["check"]["elements"]:
        if el["element_id"] == "C1a":
            el["evidence"] = [{"page": 3, "quote": "Severe low back pain for ten years"}]
    c1 = rule(run(fixture_responses), "C1")
    with pytest.raises(ReviewError, match="failed verification"):
        review_rule(c1, "confirm")
    assert review_rule(c1, "confirm", reason="Checked page 3: chief complaint documents low back pain.")


def test_referral_requires_a_reason(rules):
    with pytest.raises(ReviewError, match="needs a reason"):
        case_action(rules, _confirm_all(rules), "refer_to_medical_director")
    assert case_action(rules, _confirm_all(rules), "refer_to_medical_director", note="C3: prior MRI 06/18/2026.")


def test_deny_is_not_an_action(rules):
    with pytest.raises(ReviewError, match="not an allowed case action"):
        case_action(rules, _confirm_all(rules), "deny", note="x")


def test_information_request_lists_only_missing_parts(run, fixture_responses):
    result = run(fixture_responses)
    text = draft_information_request(result["rules"], load_criteria(), result["details"])
    assert "how MRI results would change the treatment plan" in text
    assert "lumbar spine MRI or CT" not in text  # C3 is not met, not missing
    assert "fixed template" in text


def test_approve_is_blocked_when_the_ai_produced_no_rule_results():
    assert approve_blockers([], {}) != []
    with pytest.raises(ReviewError, match="Approve is not available"):
        case_action([], {}, "approve")
    assert case_action([], {}, "refer_to_medical_director", note="AI check failed; manual review needed.")


# Regression (Nov 9): the form had a Confirm/Override radio AND a status dropdown. Changing
# the dropdown while the radio said Confirm saved a confirm with no reason. The app now uses
# one control, the final status, through review_from_status.
def test_choosing_a_different_status_is_an_override_that_needs_a_reason(rules):
    from src.review import review_from_status
    c1 = next(r for r in rules if r["id"] == "C1")  # AI status: met
    with pytest.raises(ReviewError, match="An override of C1 needs a reason"):
        review_from_status(c1, "not_met")
    rec = review_from_status(c1, "not_met", reason="Exam on page 4 was done by phone; not a true exam.")
    assert rec["action"] == "override" and rec["final_status"] == "not_met"


def test_choosing_the_ai_status_is_a_confirm_without_a_reason(rules):
    from src.review import review_from_status
    c4 = next(r for r in rules if r["id"] == "C4")  # AI status: missing
    rec = review_from_status(c4, "missing")
    assert rec["action"] == "confirm" and rec["reason"] == ""


def test_changing_a_saved_review_needs_a_reason_even_back_to_the_ai_status(rules):
    from src.review import review_from_status
    c4 = next(r for r in rules if r["id"] == "C4")  # AI status: missing
    first = review_from_status(c4, "met", reason="Provider called: results decide on an epidural injection.")
    # Switching back to the AI's own status is a confirm, but it changes a saved decision.
    with pytest.raises(ReviewError, match="Changing your saved review of C4 needs a reason"):
        review_from_status(c4, "missing", previous=first)
    assert review_from_status(c4, "missing", reason="Call note not in the record yet.", previous=first)


def test_resaving_the_same_status_needs_no_new_reason(rules):
    from src.review import review_from_status
    c4 = next(r for r in rules if r["id"] == "C4")
    first = review_from_status(c4, "missing")
    assert review_from_status(c4, "missing", previous=first)["final_status"] == "missing"
