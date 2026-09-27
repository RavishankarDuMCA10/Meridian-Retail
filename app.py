#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

APP_DIR = Path(__file__).parent
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
ALLOWED_REVIEW_STATUSES = {"READY_FOR_HUMAN_REVIEW", "NEEDS_INFORMATION", "BLOCKED"}
REQUIRED_FIELDS = {"draft_reply", "evidence_refs", "missing_information", "review_status"}

DISCLAIMER = (
    "This is a draft for human review only. No refund has been approved, "
    "no message has been sent, and no record has been changed."
)


def load_case(case_id, cases_path=None):
    cases_path = cases_path or APP_DIR / "cases.json"
    with open(cases_path) as f:
        cases = json.load(f)
    if case_id not in cases:
        raise ValueError(f"Unknown case id: {case_id}")
    return cases[case_id]


def load_policy(policy_path=None):
    policy_path = policy_path or APP_DIR / "policy.md"
    with open(policy_path) as f:
        return f.read()


def load_demo_output(case_id, demo_path=None):
    demo_path = demo_path or APP_DIR / "demo_outputs.json"
    with open(demo_path) as f:
        demo = json.load(f)
    if case_id not in demo:
        raise ValueError(f"No demo output for case id: {case_id}")
    return demo[case_id]


def missing_delivery_date_result():
    return {
        "draft_reply": (
            "Before Meridian Retail can assess whether this case falls within the "
            "two-day damage-reporting rule, please provide the delivery date. A human "
            "support agent will review the request once that information is available."
        ),
        "evidence_refs": ["P2", "P4"],
        "missing_information": ["delivery_date"],
        "review_status": "NEEDS_INFORMATION",
    }


def unavailable_result():
    return {
        "draft_reply": "",
        "evidence_refs": [],
        "missing_information": [],
        "review_status": "UNAVAILABLE",
    }


def manual_fallback_message():
    return (
        "MANUAL FALLBACK REQUIRED: the drafting assistant is unavailable. "
        "A human support agent must handle this case directly."
    )


def validate_result(data):
    if not isinstance(data, dict):
        raise ValueError("Model output must be a JSON object")
    if set(data.keys()) != REQUIRED_FIELDS:
        raise ValueError(f"Model output must have exactly these fields: {sorted(REQUIRED_FIELDS)}")
    if not isinstance(data["draft_reply"], str):
        raise ValueError("draft_reply must be a string")
    if not isinstance(data["evidence_refs"], list) or not all(isinstance(x, str) for x in data["evidence_refs"]):
        raise ValueError("evidence_refs must be a list of strings")
    if not isinstance(data["missing_information"], list) or not all(isinstance(x, str) for x in data["missing_information"]):
        raise ValueError("missing_information must be a list of strings")
    if data["review_status"] not in ALLOWED_REVIEW_STATUSES:
        raise ValueError(f"review_status must be one of {sorted(ALLOWED_REVIEW_STATUSES)}")
    return data


def build_prompt(case, policy_text):
    return f"""You are drafting a customer support reply for Meridian Retail. A human \
agent reviews every draft before anything is sent - you are not sending anything yourself.

Use ONLY the supplied facts and the supplied policy below. Do not invent facts, dates, \
or policy rules that are not given here.

SUPPLIED FACTS (JSON):
{json.dumps(case, indent=2)}

SUPPLIED POLICY:
{policy_text}

Respond with ONLY a single JSON object (no markdown fences, no commentary) with exactly \
these four keys:
- "draft_reply": string, the proposed reply text for the human reviewer to check
- "evidence_refs": list of policy IDs (e.g. "P1") that justify the draft
- "missing_information": list of field names still needed from the customer
- "review_status": one of "READY_FOR_HUMAN_REVIEW", "NEEDS_INFORMATION", "BLOCKED"

Rules:
- If issue_status is "open", the draft must not claim the issue is resolved.
- Never state or imply that a refund has been approved, a message has been sent, or a \
record has been changed - this assistant only drafts for human review.
- Return only the JSON object."""


def call_model(model_fn, case, policy_text):
    prompt = build_prompt(case, policy_text)
    raw_text = model_fn(prompt)
    data = json.loads(raw_text)
    return validate_result(data)


def make_real_model_fn(client, model):
    def _call(prompt):
        response = client.messages.create(
            model=model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    return _call


def build_default_model_fn():
    load_dotenv(APP_DIR / ".env")
    api_key = os.getenv("APP_ANTHROPIC_API_KEY")
    model = os.getenv("APP_ANTHROPIC_MODEL", DEFAULT_MODEL)
    if not api_key:
        raise RuntimeError("APP_ANTHROPIC_API_KEY is not set. Run: python setup_env.py")
    client = anthropic.Anthropic(api_key=api_key, timeout=20, max_retries=0)
    return make_real_model_fn(client, model)


def print_section(title, body):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")
    print(body)


def format_case_facts(case):
    return "\n".join(f"  {key}: {json.dumps(value)}" for key, value in case.items())


def print_draft_result(result, notice=None):
    body = json.dumps(result, indent=2)
    if notice:
        body = notice + "\n\n" + body
    print_section("DRAFT RESULT FOR HUMAN REVIEW", body)
    print(DISCLAIMER)


def run(case_id, simulate_timeout=False, offline_demo=False, model_fn=None):
    case = load_case(case_id)
    policy_text = load_policy()

    print_section("SUPPLIED FACTS", format_case_facts(case))
    print_section("SUPPLIED POLICY", policy_text)

    if simulate_timeout:
        result = unavailable_result()
        print_draft_result(result, notice=manual_fallback_message())
        return result

    if offline_demo:
        result = load_demo_output(case_id)
        print_draft_result(result, notice="NOTE: No model API was called. This is a prerecorded synthetic demo output.")
        return result

    if not case.get("delivery_date"):
        result = missing_delivery_date_result()
        print_draft_result(result)
        return result

    try:
        active_model_fn = model_fn or build_default_model_fn()
        result = call_model(active_model_fn, case, policy_text)
        print_draft_result(result)
        return result
    except (anthropic.APIError, RuntimeError, json.JSONDecodeError, ValueError) as exc:
        result = unavailable_result()
        print_draft_result(result, notice=f"{manual_fallback_message()} ({type(exc).__name__})")
        return result


def main():
    parser = argparse.ArgumentParser(description="Meridian Retail support-draft review tool")
    parser.add_argument("--case", required=True, choices=["C1", "C2", "C3"], help="Case ID")
    parser.add_argument("--simulate-timeout", action="store_true", help="Simulate an unavailable model API, no call made")
    parser.add_argument("--offline-demo", action="store_true", help="Show a prerecorded demo result, no call made")
    args = parser.parse_args()

    if args.simulate_timeout and args.offline_demo:
        parser.error("--simulate-timeout and --offline-demo cannot be used together")

    try:
        result = run(args.case, simulate_timeout=args.simulate_timeout, offline_demo=args.offline_demo)
    except Exception as exc:  # last-resort safety net: never show a traceback
        result = unavailable_result()
        print_draft_result(result, notice=f"{manual_fallback_message()} ({type(exc).__name__})")

    sys.exit(0 if result["review_status"] != "UNAVAILABLE" else 1)


if __name__ == "__main__":
    main()
