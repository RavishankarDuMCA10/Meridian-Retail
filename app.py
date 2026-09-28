#!/usr/bin/env python3
import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).parent
DOCS_DIR = APP_DIR / "docs"
DEFAULT_MODEL = "qwen3:4b"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
OLLAMA_TIMEOUT_SECONDS = 60
RETURN_WINDOW_HOURS = 78
ALLOWED_REVIEW_STATUSES = {"READY_FOR_HUMAN_REVIEW", "NEEDS_INFORMATION", "BLOCKED"}

# The output contract from docs/contractDefinitions.md. The original four
# fields (draft_reply, evidence_refs, missing_information, review_status)
# are preserved verbatim inside this larger set, per docs/task.md's
# "Output contract" section.
REQUIRED_FIELDS = {
    "case_id",
    "case_summary",
    "known_facts",
    "evidence_refs",
    "evidence_links",
    "missing_information",
    "conflicting_information",
    "draft_reply",
    "review_status",
    "human_action_required",
}

# Which evidence_map.json category backs each case.json field, so known_facts
# entries can be built with a correct source_id without inventing one.
FACT_SOURCE_CATEGORY = {
    "case_id": "support_queue",
    "customer_question": "support_queue",
    "order_id": "order_record",
    "product": "order_record",
    "delivery_date": "order_record",
    "issue_status": "issue_record",
    "issue_details": "issue_record",
}

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
    policy_path = policy_path or DOCS_DIR / "policy.md"
    with open(policy_path) as f:
        return f.read()


def load_task(task_path=None):
    task_path = task_path or DOCS_DIR / "task.md"
    with open(task_path) as f:
        return f.read()


def load_definitions(definitions_path=None):
    definitions_path = definitions_path or DOCS_DIR / "definitions.md"
    with open(definitions_path) as f:
        return f.read()


def load_contract_definitions(contract_path=None):
    contract_path = contract_path or DOCS_DIR / "contractDefinitions.md"
    with open(contract_path) as f:
        return f.read()


def load_evidence_map(evidence_map_path=None):
    evidence_map_path = evidence_map_path or APP_DIR / "evidence_map.json"
    with open(evidence_map_path) as f:
        return json.load(f)


def load_demo_output(case_id, demo_path=None):
    demo_path = demo_path or APP_DIR / "demo_outputs.json"
    with open(demo_path) as f:
        demo = json.load(f)
    if case_id not in demo:
        raise ValueError(f"No demo output for case id: {case_id}")
    return demo[case_id]


def source_ids_for_case(case):
    """The exact source_id strings evidence_map.json entries resolve to for
    this case, e.g. "support_queue:C2", "order_record:MR-1088"."""
    return {
        "support_queue": f"support_queue:{case['case_id']}",
        "order_record": f"order_record:{case['order_id']}",
        "issue_record": f"issue_record:{case['case_id']}",
        "policy_register": "policy_register:docs/policy.md",
    }


def build_known_facts(case):
    """known_facts entries built only from values already present in
    cases.json - each paired with the source_id that evidence_map.json
    says backs it. Missing values are left for missing_information."""
    sources = source_ids_for_case(case)
    facts = []
    for field, value in case.items():
        if value is None:
            continue
        category = FACT_SOURCE_CATEGORY.get(field)
        if category is None:
            continue
        facts.append({
            "field": field,
            "value": value if isinstance(value, str) else json.dumps(value),
            "source_id": sources[category],
        })
    return facts


def missing_delivery_date_result(case):
    sources = source_ids_for_case(case)
    return {
        "case_id": case["case_id"],
        "case_summary": (
            f"Customer asks: \"{case['customer_question']}\" The delivery date is "
            f"not on record, so the {RETURN_WINDOW_HOURS}-hour rule cannot be "
            f"applied yet."
        ),
        "known_facts": build_known_facts(case),
        "evidence_refs": ["P2", "P4"],
        "evidence_links": [
            {
                "claim": f"The delivery date is required to apply the {RETURN_WINDOW_HOURS}-hour rule.",
                "source_id": sources["policy_register"],
            },
            {
                "claim": "This assistant drafts for human review only.",
                "source_id": sources["policy_register"],
            },
        ],
        "missing_information": ["delivery_date"],
        "conflicting_information": [],
        "draft_reply": (
            f"Before Meridian Retail can assess whether this case falls within the "
            f"{RETURN_WINDOW_HOURS}-hour damage-reporting window, please provide the "
            f"delivery date. A human support agent will review the request once that "
            f"information is available."
        ),
        "review_status": "NEEDS_INFORMATION",
        "human_action_required": (
            "A human support agent must obtain and confirm the delivery date before "
            "the dependent review continues."
        ),
    }


def hours_since_delivery(delivery_date, now=None):
    """Hours elapsed between delivery_date ("YYYY-MM-DD") and now.

    Returns None if delivery_date is missing or cannot be parsed.
    """
    if not delivery_date:
        return None
    try:
        delivered_at = datetime.strptime(delivery_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    current_time = now or datetime.now()
    return (current_time - delivered_at).total_seconds() / 3600


def is_within_return_window(delivery_date, now=None, window_hours=RETURN_WINDOW_HOURS):
    hours = hours_since_delivery(delivery_date, now=now)
    if hours is None:
        return False
    return 0 <= hours <= window_hours


def out_of_window_result(case, hours_since):
    sources = source_ids_for_case(case)
    return {
        "case_id": case["case_id"],
        "case_summary": (
            f"Customer asks: \"{case['customer_question']}\" Delivery was recorded "
            f"on {case['delivery_date']}, more than {RETURN_WINDOW_HOURS} hours "
            f"before this review."
        ),
        "known_facts": build_known_facts(case),
        "evidence_refs": ["P1", "P2"],
        "evidence_links": [
            {
                "claim": (
                    f"Damage reported within {RETURN_WINDOW_HOURS} hours of delivery "
                    f"can be referred for human return review."
                ),
                "source_id": sources["policy_register"],
            },
        ],
        "missing_information": [],
        "conflicting_information": [],
        "draft_reply": (
            f"Thank you for the details. Our records show this order was delivered "
            f"on {case['delivery_date']}, which is more than {RETURN_WINDOW_HOURS} "
            f"hours ago. Under policy P1, damage must be reported within "
            f"{RETURN_WINDOW_HOURS} hours of delivery to be referred for a human "
            f"return review, so this request falls outside that window and cannot "
            f"be referred for a refund review. A human support agent can still "
            f"advise on any other options available."
        ),
        "review_status": "BLOCKED",
        "human_action_required": (
            "A human support agent can advise the customer on options outside the "
            "standard return window."
        ),
    }


def unavailable_result(case_id=None):
    return {
        "case_id": case_id or "",
        "case_summary": "",
        "known_facts": [],
        "evidence_refs": [],
        "evidence_links": [],
        "missing_information": [],
        "conflicting_information": [],
        "draft_reply": "",
        "review_status": "UNAVAILABLE",
        "human_action_required": "A human support agent must handle this case directly.",
    }


def manual_fallback_message():
    return (
        "MANUAL FALLBACK REQUIRED: the drafting assistant is unavailable. "
        "A human support agent must handle this case directly."
    )


def _is_str_list(value):
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def validate_result(data):
    if not isinstance(data, dict):
        raise ValueError("Model output must be a JSON object")
    if set(data.keys()) != REQUIRED_FIELDS:
        raise ValueError(f"Model output must have exactly these fields: {sorted(REQUIRED_FIELDS)}")
    if not isinstance(data["case_id"], str):
        raise ValueError("case_id must be a string")
    if not isinstance(data["case_summary"], str):
        raise ValueError("case_summary must be a string")
    if not isinstance(data["known_facts"], list) or not all(
        isinstance(item, dict) and {"field", "value", "source_id"} <= set(item.keys())
        and isinstance(item["field"], str) and isinstance(item["value"], str) and isinstance(item["source_id"], str)
        for item in data["known_facts"]
    ):
        raise ValueError("known_facts must be a list of {field, value, source_id} objects")
    if not _is_str_list(data["evidence_refs"]):
        raise ValueError("evidence_refs must be a list of strings")
    if not isinstance(data["evidence_links"], list) or not all(
        isinstance(item, dict) and {"claim", "source_id"} <= set(item.keys())
        and isinstance(item["claim"], str) and isinstance(item["source_id"], str)
        for item in data["evidence_links"]
    ):
        raise ValueError("evidence_links must be a list of {claim, source_id} objects")
    if not _is_str_list(data["missing_information"]):
        raise ValueError("missing_information must be a list of strings")
    if not isinstance(data["conflicting_information"], list) or not all(
        isinstance(item, dict) and {"description", "source_ids"} <= set(item.keys())
        and isinstance(item["description"], str) and _is_str_list(item["source_ids"])
        for item in data["conflicting_information"]
    ):
        raise ValueError("conflicting_information must be a list of {description, source_ids} objects")
    if not isinstance(data["draft_reply"], str):
        raise ValueError("draft_reply must be a string")
    if data["review_status"] not in ALLOWED_REVIEW_STATUSES:
        raise ValueError(f"review_status must be one of {sorted(ALLOWED_REVIEW_STATUSES)}")
    if not isinstance(data["human_action_required"], str):
        raise ValueError("human_action_required must be a string")
    return data


def build_prompt(case, policy_text, task_text, definitions_text, contract_text):
    sources = source_ids_for_case(case)
    return f"""You are drafting a customer support reply for Meridian Retail. A human \
agent reviews every draft before anything is sent - you are not sending anything yourself.

Use ONLY the supplied task, definitions, output contract, policy and facts below. Do \
not invent facts, dates, policy rules, or source IDs that are not given here.

SUPPLIED TASK (docs/task.md):
{task_text}

SUPPLIED DEFINITIONS (docs/definitions.md):
{definitions_text}

SUPPLIED OUTPUT CONTRACT (docs/contractDefinitions.md):
{contract_text}

SUPPLIED POLICY (docs/policy.md):
{policy_text}

SUPPLIED FACTS (JSON):
{json.dumps(case, indent=2)}

SUPPLIED SOURCE IDS for this case - use these exact strings, and only these, for every \
source_id / source_ids value:
{json.dumps(sources, indent=2)}

Respond with ONLY a single JSON object (no markdown fences, no commentary) with exactly \
these ten keys:
- "case_id": string, matches the selected case
- "case_summary": string, summarises only supplied evidence
- "known_facts": list of objects, each with "field", "value" and a "source_id" from the \
supplied source IDs above
- "evidence_refs": list of policy IDs (e.g. "P1") that justify the draft
- "evidence_links": list of objects, each with "claim" and a supplied "source_id"
- "missing_information": list of field names still needed from the customer
- "conflicting_information": list of objects, each with "description" and "source_ids"; \
empty list when nothing conflicts
- "draft_reply": string, the proposed reply text for the human reviewer to check
- "review_status": one of "READY_FOR_HUMAN_REVIEW", "NEEDS_INFORMATION", "BLOCKED"
- "human_action_required": string naming the next human-owned step, without inventing a person

Rules:
- If issue_status is "open", the draft must not claim the issue is resolved.
- Never state or imply that a refund has been approved, a message has been sent, or a \
record has been changed - this assistant only drafts for human review.
- Every source_id you use must be one of the supplied source IDs above.
- Return only the JSON object."""


def call_model(model_fn, case, policy_text, task_text, definitions_text, contract_text):
    prompt = build_prompt(case, policy_text, task_text, definitions_text, contract_text)
    raw_text = model_fn(prompt)
    data = json.loads(raw_text)
    return validate_result(data)


RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "case_id": {"type": "string"},
        "case_summary": {"type": "string"},
        "known_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "value": {"type": "string"},
                    "source_id": {"type": "string"},
                },
                "required": ["field", "value", "source_id"],
            },
        },
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
        "evidence_links": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "source_id": {"type": "string"},
                },
                "required": ["claim", "source_id"],
            },
        },
        "missing_information": {"type": "array", "items": {"type": "string"}},
        "conflicting_information": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["description", "source_ids"],
            },
        },
        "draft_reply": {"type": "string"},
        "review_status": {"type": "string", "enum": sorted(ALLOWED_REVIEW_STATUSES)},
        "human_action_required": {"type": "string"},
    },
    "required": sorted(REQUIRED_FIELDS),
}


def make_real_model_fn(host, model, timeout=OLLAMA_TIMEOUT_SECONDS):
    def _call(prompt):
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "format": RESULT_SCHEMA,
            "options": {"temperature": 0, "num_predict": 500},
        }
        request = urllib.request.Request(
            f"{host.rstrip('/')}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read())
        return body["message"]["content"]

    return _call


def build_default_model_fn():
    load_dotenv(APP_DIR / ".env")
    host = os.getenv("APP_OLLAMA_HOST", DEFAULT_OLLAMA_HOST)
    model = os.getenv("APP_OLLAMA_MODEL", DEFAULT_MODEL)
    return make_real_model_fn(host, model)


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


def run(case_id, simulate_timeout=False, offline_demo=False, model_fn=None, now=None):
    case = load_case(case_id)
    task_text = load_task()
    definitions_text = load_definitions()
    contract_text = load_contract_definitions()
    policy_text = load_policy()

    print_section("SUPPLIED FACTS", format_case_facts(case))
    print_section("SUPPLIED TASK", task_text)
    print_section("SUPPLIED DEFINITIONS", definitions_text)
    print_section("SUPPLIED OUTPUT CONTRACT", contract_text)
    print_section("SUPPLIED POLICY", policy_text)

    if simulate_timeout:
        result = unavailable_result(case_id)
        print_draft_result(result, notice=manual_fallback_message())
        return result

    if offline_demo:
        result = load_demo_output(case_id)
        print_draft_result(result, notice="NOTE: No model API was called. This is a prerecorded synthetic demo output.")
        return result

    if not case.get("delivery_date"):
        result = missing_delivery_date_result(case)
        print_draft_result(result)
        return result

    hours_since = hours_since_delivery(case["delivery_date"], now=now)
    if hours_since is None or not (0 <= hours_since <= RETURN_WINDOW_HOURS):
        result = out_of_window_result(case, hours_since)
        print_draft_result(result)
        return result

    try:
        active_model_fn = model_fn or build_default_model_fn()
        result = call_model(active_model_fn, case, policy_text, task_text, definitions_text, contract_text)
        print_draft_result(result)
        return result
    except (OSError, KeyError, RuntimeError, json.JSONDecodeError, ValueError) as exc:
        result = unavailable_result(case_id)
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
        result = unavailable_result(args.case)
        print_draft_result(result, notice=f"{manual_fallback_message()} ({type(exc).__name__})")

    sys.exit(0 if result["review_status"] != "UNAVAILABLE" else 1)


if __name__ == "__main__":
    main()
