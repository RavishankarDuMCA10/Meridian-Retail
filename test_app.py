import json

import pytest

import app


def fake_model_fn_returning(payload):
    def _fn(prompt):
        return json.dumps(payload)

    return _fn


def failing_model_fn(*args, **kwargs):
    raise AssertionError("The model must not be called for this case")


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


def test_load_demo_output_has_all_cases_with_required_fields():
    for case_id in ("C1", "C2", "C3"):
        result = app.load_demo_output(case_id)
        assert set(result.keys()) == {
            "draft_reply", "evidence_refs", "missing_information", "review_status",
        }


def test_load_demo_output_unknown_id_raises():
    with pytest.raises(ValueError):
        app.load_demo_output("C999")


# ---- validate_result ----

def test_validate_result_accepts_well_formed_data():
    data = {
        "draft_reply": "ok",
        "evidence_refs": ["P1"],
        "missing_information": [],
        "review_status": "READY_FOR_HUMAN_REVIEW",
    }
    assert app.validate_result(data) == data


@pytest.mark.parametrize("broken", [
    "not a dict",
    {"draft_reply": "ok"},
    {"draft_reply": 1, "evidence_refs": [], "missing_information": [], "review_status": "BLOCKED"},
    {"draft_reply": "ok", "evidence_refs": "P1", "missing_information": [], "review_status": "BLOCKED"},
    {"draft_reply": "ok", "evidence_refs": [], "missing_information": [1], "review_status": "BLOCKED"},
    {"draft_reply": "ok", "evidence_refs": [], "missing_information": [], "review_status": "NOT_A_STATUS"},
    {"draft_reply": "ok", "evidence_refs": [], "missing_information": [], "review_status": "BLOCKED", "extra": 1},
])
def test_validate_result_rejects_malformed_data(broken):
    with pytest.raises(ValueError):
        app.validate_result(broken)


# ---- call_model, driven by a fake model function (no network) ----

def test_call_model_success_c1():
    case = app.load_case("C1")
    policy = app.load_policy()
    model_fn = fake_model_fn_returning({
        "draft_reply": "We can refer this for human return review.",
        "evidence_refs": ["P1", "P2"],
        "missing_information": [],
        "review_status": "READY_FOR_HUMAN_REVIEW",
    })
    result = app.call_model(model_fn, case, policy)
    assert result["review_status"] == "READY_FOR_HUMAN_REVIEW"
    assert result["evidence_refs"] == ["P1", "P2"]


def test_call_model_invalid_json_raises():
    case = app.load_case("C1")
    policy = app.load_policy()
    with pytest.raises(json.JSONDecodeError):
        app.call_model(lambda prompt: "not json", case, policy)


def test_call_model_invalid_structure_raises():
    case = app.load_case("C1")
    policy = app.load_policy()
    with pytest.raises(ValueError):
        app.call_model(fake_model_fn_returning({"draft_reply": "ok"}), case, policy)


# ---- run(): end-to-end orchestration and precedence rules ----

def test_run_c1_ready_for_review(capsys):
    model_fn = fake_model_fn_returning({
        "draft_reply": "We can refer this for human return review.",
        "evidence_refs": ["P1", "P2"],
        "missing_information": [],
        "review_status": "READY_FOR_HUMAN_REVIEW",
    })
    result = app.run("C1", model_fn=model_fn)
    out = capsys.readouterr().out
    assert result["review_status"] == "READY_FOR_HUMAN_REVIEW"
    assert "SUPPLIED FACTS" in out
    assert "SUPPLIED POLICY" in out
    assert "DRAFT RESULT FOR HUMAN REVIEW" in out


def test_run_simulate_timeout_is_unavailable_and_makes_no_call():
    result = app.run("C1", simulate_timeout=True, model_fn=failing_model_fn)
    assert result["review_status"] == "UNAVAILABLE"
    assert result["draft_reply"] == ""


def test_run_offline_demo_makes_no_call_and_says_so(capsys):
    result = app.run("C1", offline_demo=True, model_fn=failing_model_fn)
    out = capsys.readouterr().out
    assert result == app.load_demo_output("C1")
    assert "No model API was called" in out


def test_run_model_failure_yields_unavailable_not_a_traceback():
    def boom(prompt):
        raise RuntimeError("network exploded")

    result = app.run("C1", model_fn=boom)
    assert result["review_status"] == "UNAVAILABLE"
    assert result["draft_reply"] == ""


def test_run_model_returning_invalid_output_yields_unavailable():
    result = app.run("C1", model_fn=fake_model_fn_returning({"draft_reply": "incomplete"}))
    assert result["review_status"] == "UNAVAILABLE"


def test_c2_missing_delivery_date_is_deterministic_and_skips_the_model():
    result = app.run("C2", model_fn=failing_model_fn)
    assert result == app.missing_delivery_date_result()
    assert result["review_status"] == "NEEDS_INFORMATION"
    assert result["missing_information"] == ["delivery_date"]
    assert result["evidence_refs"] == ["P2", "P4"]


def test_c2_simulate_timeout_still_takes_precedence_over_missing_date():
    result = app.run("C2", simulate_timeout=True, model_fn=failing_model_fn)
    assert result["review_status"] == "UNAVAILABLE"


def test_c2_offline_demo_still_takes_precedence_over_missing_date():
    result = app.run("C2", offline_demo=True, model_fn=failing_model_fn)
    assert result == app.load_demo_output("C2")
