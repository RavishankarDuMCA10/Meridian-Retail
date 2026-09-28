import json
from datetime import datetime

import pytest

import app

# Fixed reference "now" values so tests don't depend on the real wall clock.
# C1 delivery_date is "2026-09-15" (supplied fact - never altered by the tool).
NOW_WITHIN_WINDOW = datetime(2026, 9, 17, 6, 0, 0)  # 54h after C1's delivery_date
NOW_OUTSIDE_WINDOW = datetime(2026, 10, 5, 12, 0, 0)  # ~20 days after C1's delivery_date


def fake_model_fn_returning(payload):
    def _fn(prompt):
        return json.dumps(payload)

    return _fn


def failing_model_fn(*args, **kwargs):
    raise AssertionError("The model must not be called for this case")


def full_result(**overrides):
    """A complete, contract-valid result payload to use as fake model output."""
    data = {
        "case_id": "C1",
        "case_summary": "Summary.",
        "known_facts": [
            {"field": "case_id", "value": "C1", "source_id": "support_queue:C1"},
        ],
        "evidence_refs": ["P1", "P2"],
        "evidence_links": [
            {
                "claim": "Damage reported within 78 hours of delivery can be referred for human return review.",
                "source_id": "policy_register:docs/policy.md",
            },
        ],
        "missing_information": [],
        "conflicting_information": [],
        "draft_reply": "We can refer this for human return review.",
        "review_status": "READY_FOR_HUMAN_REVIEW",
        "human_action_required": "A human support agent reviews the case.",
    }
    data.update(overrides)
    return data


# ---- loading the input files ----

def test_load_case_c1():
    case = app.load_case("C1")
    assert case["case_id"] == "C1"
    assert case["order_id"] == "MR-1042"
    assert case["delivery_date"] == "2026-09-15"


def test_load_case_c2_has_no_delivery_date():
    case = app.load_case("C2")
    assert case["case_id"] == "C2"
    assert case["delivery_date"] is None


def test_load_case_c3():
    case = app.load_case("C3")
    assert case["case_id"] == "C3"
    assert case["issue_status"] == "open"


def test_load_case_unknown_id_raises():
    with pytest.raises(ValueError):
        app.load_case("C999")


def test_load_policy_contains_all_rules():
    policy = app.load_policy()
    for rule_id in ("P1", "P2", "P3", "P4"):
        assert rule_id in policy


def test_load_task_names_the_evidence_and_output_contract():
    task = app.load_task()
    assert "Output contract" in task
    assert "support_queue:C2" in task


def test_load_definitions_contains_review_status_terms():
    definitions = app.load_definitions()
    for term in ("READY_FOR_HUMAN_REVIEW", "NEEDS_INFORMATION", "BLOCKED"):
        assert term in definitions


def test_load_contract_definitions_lists_all_required_fields():
    contract = app.load_contract_definitions()
    for field in app.REQUIRED_FIELDS:
        assert f"`{field}`" in contract


def test_load_evidence_map_has_all_source_categories():
    evidence_map = app.load_evidence_map()
    assert set(evidence_map.keys()) == {
        "support_queue", "order_record", "issue_record", "policy_register",
    }


def test_load_demo_output_has_all_cases_with_required_fields():
    for case_id in ("C1", "C2", "C3"):
        result = app.load_demo_output(case_id)
        assert set(result.keys()) == app.REQUIRED_FIELDS


def test_load_demo_output_unknown_id_raises():
    with pytest.raises(ValueError):
        app.load_demo_output("C999")


# ---- source_ids_for_case / build_known_facts ----

def test_source_ids_for_case_c2():
    case = app.load_case("C2")
    assert app.source_ids_for_case(case) == {
        "support_queue": "support_queue:C2",
        "order_record": "order_record:MR-1088",
        "issue_record": "issue_record:C2",
        "policy_register": "policy_register:docs/policy.md",
    }


def test_build_known_facts_skips_fields_that_are_missing():
    case = app.load_case("C2")  # delivery_date is None
    facts = app.build_known_facts(case)
    fields = {fact["field"] for fact in facts}
    assert "delivery_date" not in fields
    assert "case_id" in fields
    evidence_map = app.load_evidence_map()
    for fact in facts:
        assert fact["source_id"].split(":", 1)[0] in evidence_map


def test_build_known_facts_includes_delivery_date_when_present():
    case = app.load_case("C1")
    facts = app.build_known_facts(case)
    delivery_fact = next(f for f in facts if f["field"] == "delivery_date")
    assert delivery_fact["value"] == "2026-09-15"
    assert delivery_fact["source_id"] == "order_record:MR-1042"


# ---- validate_result ----

def test_validate_result_accepts_well_formed_data():
    data = full_result()
    assert app.validate_result(data) == data


def test_validate_result_rejects_non_dict():
    with pytest.raises(ValueError):
        app.validate_result("not a dict")


@pytest.mark.parametrize("mutate", [
    lambda d: d.pop("case_summary"),
    lambda d: d.update(draft_reply=1),
    lambda d: d.update(evidence_refs="P1"),
    lambda d: d.update(missing_information=[1]),
    lambda d: d.update(known_facts=[{"field": "x", "value": "y"}]),  # missing source_id
    lambda d: d.update(evidence_links=[{"claim": "x"}]),  # missing source_id
    lambda d: d.update(conflicting_information=[{"description": "x", "source_ids": [1]}]),
    lambda d: d.update(review_status="NOT_A_STATUS"),
    lambda d: d.update(human_action_required=1),
    lambda d: d.update(extra_field=1),
])
def test_validate_result_rejects_malformed_data(mutate):
    data = full_result()
    mutate(data)
    with pytest.raises(ValueError):
        app.validate_result(data)


# ---- call_model, driven by a fake model function (no network) ----

def test_call_model_success_c1():
    case = app.load_case("C1")
    result = app.call_model(
        fake_model_fn_returning(full_result()),
        case, app.load_policy(), app.load_task(), app.load_definitions(), app.load_contract_definitions(),
    )
    assert result["review_status"] == "READY_FOR_HUMAN_REVIEW"
    assert result["evidence_refs"] == ["P1", "P2"]


def test_call_model_invalid_json_raises():
    case = app.load_case("C1")
    with pytest.raises(json.JSONDecodeError):
        app.call_model(
            lambda prompt: "not json",
            case, app.load_policy(), app.load_task(), app.load_definitions(), app.load_contract_definitions(),
        )


def test_call_model_invalid_structure_raises():
    case = app.load_case("C1")
    with pytest.raises(ValueError):
        app.call_model(
            fake_model_fn_returning({"draft_reply": "ok"}),
            case, app.load_policy(), app.load_task(), app.load_definitions(), app.load_contract_definitions(),
        )


# ---- run(): end-to-end orchestration and precedence rules ----

def test_run_c1_ready_for_review(capsys):
    model_fn = fake_model_fn_returning(full_result())
    result = app.run("C1", model_fn=model_fn, now=NOW_WITHIN_WINDOW)
    out = capsys.readouterr().out
    assert result["review_status"] == "READY_FOR_HUMAN_REVIEW"
    assert "SUPPLIED FACTS" in out
    assert "SUPPLIED TASK" in out
    assert "SUPPLIED DEFINITIONS" in out
    assert "SUPPLIED OUTPUT CONTRACT" in out
    assert "SUPPLIED POLICY" in out
    assert "DRAFT RESULT FOR HUMAN REVIEW" in out


def test_run_simulate_timeout_is_unavailable_and_makes_no_call():
    result = app.run("C1", simulate_timeout=True, model_fn=failing_model_fn)
    assert result["review_status"] == "UNAVAILABLE"
    assert result["draft_reply"] == ""
    assert result["case_id"] == "C1"


def test_run_offline_demo_makes_no_call_and_says_so(capsys):
    result = app.run("C1", offline_demo=True, model_fn=failing_model_fn)
    out = capsys.readouterr().out
    assert result == app.load_demo_output("C1")
    assert "No model API was called" in out


def test_run_model_failure_yields_unavailable_not_a_traceback():
    def boom(prompt):
        raise RuntimeError("network exploded")

    result = app.run("C1", model_fn=boom, now=NOW_WITHIN_WINDOW)
    assert result["review_status"] == "UNAVAILABLE"
    assert result["draft_reply"] == ""


def test_run_model_returning_invalid_output_yields_unavailable():
    result = app.run(
        "C1",
        model_fn=fake_model_fn_returning({"draft_reply": "incomplete"}),
        now=NOW_WITHIN_WINDOW,
    )
    assert result["review_status"] == "UNAVAILABLE"


def test_c2_missing_delivery_date_is_deterministic_and_skips_the_model():
    case = app.load_case("C2")
    result = app.run("C2", model_fn=failing_model_fn)
    assert result == app.missing_delivery_date_result(case)
    assert result["review_status"] == "NEEDS_INFORMATION"
    assert result["missing_information"] == ["delivery_date"]
    assert result["evidence_refs"] == ["P2", "P4"]


def test_c2_simulate_timeout_still_takes_precedence_over_missing_date():
    result = app.run("C2", simulate_timeout=True, model_fn=failing_model_fn)
    assert result["review_status"] == "UNAVAILABLE"


def test_c2_offline_demo_still_takes_precedence_over_missing_date():
    result = app.run("C2", offline_demo=True, model_fn=failing_model_fn)
    assert result == app.load_demo_output("C2")


# ---- 78-hour return window (policy P1/P2) ----

def test_hours_since_delivery_computes_elapsed_hours():
    now = datetime(2026, 9, 17, 6, 0, 0)
    assert app.hours_since_delivery("2026-09-15", now=now) == 54.0


def test_hours_since_delivery_returns_none_for_missing_or_bad_date():
    assert app.hours_since_delivery(None) is None
    assert app.hours_since_delivery("") is None
    assert app.hours_since_delivery("not-a-date") is None


def test_is_within_return_window_true_inside_78_hours():
    assert app.is_within_return_window("2026-09-15", now=NOW_WITHIN_WINDOW)


def test_is_within_return_window_false_outside_78_hours():
    assert not app.is_within_return_window("2026-09-15", now=NOW_OUTSIDE_WINDOW)


def test_is_within_return_window_false_for_future_delivery_date():
    now = datetime(2026, 9, 10, 0, 0, 0)
    assert not app.is_within_return_window("2026-09-15", now=now)


def test_c1_outside_78_hour_window_is_deterministic_and_skips_the_model():
    result = app.run("C1", model_fn=failing_model_fn, now=NOW_OUTSIDE_WINDOW)
    assert result["review_status"] == "BLOCKED"
    assert result["evidence_refs"] == ["P1", "P2"]
    assert result["missing_information"] == []
    assert result["case_id"] == "C1"


def test_c1_simulate_timeout_still_takes_precedence_over_window_check():
    result = app.run("C1", simulate_timeout=True, model_fn=failing_model_fn, now=NOW_OUTSIDE_WINDOW)
    assert result["review_status"] == "UNAVAILABLE"


def test_c1_offline_demo_still_takes_precedence_over_window_check():
    result = app.run("C1", offline_demo=True, model_fn=failing_model_fn, now=NOW_OUTSIDE_WINDOW)
    assert result == app.load_demo_output("C1")
