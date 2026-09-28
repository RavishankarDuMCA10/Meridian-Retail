# Meridian Retail

Meridian Retail's support-draft review tool is a command-line assistant
that turns a support case into a structured, evidence-linked draft reply
for a human agent to review. It applies policy deterministically, traces
every fact to its source, and surfaces missing information instead of
guessing. It never sends a message, approves a refund, or changes a
record - a minimal classroom demo, not production software.

## The context pack (`docs/`)

- `task.md` - the task itself: what evidence is in scope, the output
  contract to produce, and the missing-information / human-review rules.
- `definitions.md` - the meaning of terms used elsewhere in the pack
  (`source_id`, `known fact`, `evidence link`, the three review statuses,
  etc.).
- `contractDefinitions.md` - the ten fields the output JSON must contain
  (`case_id`, `case_summary`, `known_facts`, `evidence_refs`,
  `evidence_links`, `missing_information`, `conflicting_information`,
  `draft_reply`, `review_status`, `human_action_required`). The original
  four fields from the earlier version of this tool (`draft_reply`,
  `evidence_refs`, `missing_information`, `review_status`) are preserved
  unchanged inside this larger contract.
- `policy.md` - the P1-P4 support drafting rules.

## The source registry (`evidence_map.json`, project root)

Lives outside `docs/`, alongside `cases.json`. It records what each
`source_id` category (`support_queue`, `order_record`, `issue_record`,
`policy_register`) resolves to and which file backs it. Per-case source
IDs are built from this at run time, e.g. `support_queue:C2`,
`order_record:MR-1088`.

Every fact the tool states is paired with one of these source IDs -
nothing is asserted without a supplied source.

## What this is not

No web UI, no database, no RAG, no login flow, no agent framework, no
production integration. Just one script, its inputs, and its tests.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python setup_env.py
```

The model runs locally through [Ollama](https://ollama.com). Install it, then
pull the model:

```bash
ollama pull qwen3:4b
```

`setup_env.py` asks for the Ollama host (default `http://localhost:11434`)
and the model to use (default `qwen3:4b`), then writes a project-local
`.env` file. It's optional: without `.env` the tool uses those defaults. Copy `.env.example` if you'd rather edit it by
hand. `.env` is git-ignored.

## Running

```bash
python app.py --case C1   # or C2, C3
```

Each run prints `SUPPLIED FACTS`, `SUPPLIED TASK`, `SUPPLIED DEFINITIONS`,
`SUPPLIED OUTPUT CONTRACT`, `SUPPLIED POLICY`, and finally
`DRAFT RESULT FOR HUMAN REVIEW`.

- **C1** has a delivery date within the 78-hour return window and an open
  issue -> the model drafts a reply and the result is validated before
  display.
- **C2** has no delivery date -> the tool returns a fixed, deterministic
  "please provide the delivery date" result and **never calls the model**.
- **C3** has an open issue with a customer asking for confirmation of
  resolution -> policy P3 means the draft must not say the issue is
  resolved.

### The 78-hour return window (policy P1/P2)

The tool computes the current timestamp itself and compares it to the
order's delivery date - it never relies on the model to know "today's
date" or to do the arithmetic. This check runs before the model is called:

- If `delivery_date` is missing, the tool returns the deterministic
  "please provide the delivery date" result (see C2 above).
- If `delivery_date` is present but more than 78 hours in the past (or
  otherwise invalid), the tool returns a fixed, deterministic "outside the
  return window" result with `review_status: "BLOCKED"` and **never calls
  the model**.
- Only if `delivery_date` is within the last 78 hours does the tool call
  the model to draft the reply.

This keeps the eligibility decision itself deterministic and testable;
the model is only ever used to phrase a draft once eligibility is already
known.

### Demo modes (no model needed, no network call)

```bash
python app.py --case C1 --offline-demo       # prerecorded, labelled synthetic result
python app.py --case C1 --simulate-timeout   # simulated unavailable state
```

Both modes print an explicit notice and make no call to the model API.

### Safety behaviour

- If the model's JSON response is missing a field, has the wrong type, or
  isn't valid JSON, the tool discards it and shows the same safe
  "unavailable" state instead of a stale or malformed draft.
- If the API call itself fails (timeout, connection error, etc.), the tool
  shows the same safe "unavailable" state rather than a traceback.
- The Ollama request uses a 60 second timeout and no retries, with
  thinking disabled, temperature 0, and a JSON schema that constrains the
  output. It reads `APP_OLLAMA_HOST` / `APP_OLLAMA_MODEL` only.

## Tests

```bash
python -m pytest -q
```

All tests run offline. Model calls are replaced with a fake function passed
into `app.call_model` / `app.run` - no real network request is ever made
during the test suite.
