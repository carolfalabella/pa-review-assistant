"""AI never denies: no denial or partial-approval value exists anywhere a model
or a reviewer action could produce one. Any change that adds one fails here."""

import json

from src import review, route
from src.criteria import element_ids, load_criteria
from src.schemas import STATUSES, check_schema

FORBIDDEN = ("deny", "denied", "denial", "reject", "partial", "adverse")


def _has_forbidden(value) -> list[str]:
    text = json.dumps(value).lower()
    return [w for w in FORBIDDEN if w in text]


def test_status_enum_is_exactly_three_values():
    assert STATUSES == ("met", "not_met", "missing")


def test_model_output_schema_has_no_denial_value():
    assert _has_forbidden(check_schema(element_ids(load_criteria()))) == []


def test_case_and_rule_actions_have_no_denial_or_partial_approval():
    assert review.CASE_ACTIONS == ("approve", "request_information", "refer_to_medical_director")
    assert _has_forbidden(review.CASE_ACTIONS) == []
    assert _has_forbidden(review.RULE_ACTIONS) == []


def test_router_only_suggests_allowed_actions(run, fixture_responses):
    for scenario in ("as_is", "all_met"):
        resp = json.loads(json.dumps(fixture_responses))
        if scenario == "all_met":
            for el in resp["check"]["elements"]:
                el["status"] = "met"
            # keep quotes valid: C4a gets a real quote from page 5
            resp["check"]["elements"][-1]["evidence"] = [{"page": 5, "quote": "Order MRI lumbar spine without contrast"}]
        suggested = run(resp)["route"]["suggested_actions"]
        assert set(suggested) <= set(review.CASE_ACTIONS)


def test_router_queues_are_all_human_review():
    r = route.route(["x"], None, [])
    assert r["queue"].startswith("nurse_review")


def test_conflict_rule_excludes_change_over_time():
    # Regression: Qwen marked C1b not_met on case_003 because an exam changed
    # between August and October. The prompt must say that is not a conflict.
    from src.prompts import CHECK_SYSTEM
    assert "changes over time" in CHECK_SYSTEM and "is not a conflict" in CHECK_SYSTEM
