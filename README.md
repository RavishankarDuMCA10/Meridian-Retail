# Meridian Retail Support-Draft Review Tool

A minimal classroom demo: a CLI that drafts a support reply for a human agent
to review, using only the facts in `cases.json` and the rules in `policy.md`.

It **never** sends a message, approves a refund, or changes a record. Every
run prints the facts it used, the policy it used, and a draft result labelled
for human review.

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

`setup_env.py` asks for your Anthropic API key (input hidden, never printed)
and the model to use (default `claude-haiku-4-5-20251001`), then writes a
project-local `.env` file. Copy `.env.example` if you'd rather edit it by
hand. `.env` is git-ignored.

## Running

```bash
python app.py --case C1   # or C2, C3
```

Each run prints three sections: `SUPPLIED FACTS`, `SUPPLIED POLICY`, and
`DRAFT RESULT FOR HUMAN REVIEW`.

- **C1** has a delivery date and an open issue -> the model drafts a reply
  and the result is validated before display.
- **C2** has no delivery date -> the tool returns a fixed, deterministic
  "please provide the delivery date" result and **never calls the model**.
- **C3** has an open issue with a customer asking for confirmation of
  resolution -> policy P3 means the draft must not say the issue is
  resolved.

### Demo modes (no API key needed, no network call)

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
- The Anthropic client is created with an explicit API key, a 20 second
  timeout, and `max_retries=0`. It reads `APP_ANTHROPIC_API_KEY` /
  `APP_ANTHROPIC_MODEL` only - never the global `ANTHROPIC_API_KEY`.

## Tests

```bash
python -m pytest -q
```

All tests run offline. Model calls are replaced with a fake function passed
into `app.call_model` / `app.run` - no real network request is ever made
during the test suite.
