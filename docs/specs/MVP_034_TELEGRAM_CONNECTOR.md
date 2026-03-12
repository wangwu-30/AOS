# MVP 034: Telegram Webhook Connector (PA-CH1)

## Overview
This specification details the contract for the AgentOS Next Telegram Connector (`PA-CH1`). The channel adapter natively processes Telegram webhook payloads, safely maps them to orchestrator actions, and rejects unauthorized or structurally unsound requests at the application edge.

## Target Audience
- System Architects
- Security Auditors
- Core Runtime Developers

## Dependencies
- Must align strictly with `MVP_033_EVENT_ENVELOPE` (`EventEnvelopeV0`) constraints.
- Utilizes `agentos_next.apps.telegram_models.py` natively via DataClasses.

## Contract Schema

The Channel Adapter validates incoming JSON to conform against:
```json
{
  "update_id": "<integer>",
  "message": {
    "message_id": "<integer>",
    "date": "<integer>",
    "chat": {
      "id": "<integer>",
      "type": "<string>"
    },
    "from": {
      "id": "<integer>",
      "is_bot": "<boolean>",
      "first_name": "<string>",
      "username": "<string_or_null>"
    },
    "text": "<string>"
  }
}
```

## Governance Constraints

### 1. Zero Side-Effect Replay
- Execution with `replay_mode=True` blocks dispatch to Kernel pipeline completely.
- Webhook adapter is naturally stateless; prevents disk/network output entirely.

### 2. Error Traceback Shielding
- All extraction layer (`KeyError`, `ValueError`, `TypeError`) faults are translated gracefully to:
`HTTP 400 Bad Request: {"ok": false, "error_code": "E_CHANNEL_PAYLOAD_INVALID"}`
- Webhook token mismatch yields:
`HTTP 401 Unauthorized: {"ok": false, "error_code": "E_AUTH_FAILED"}`

### 3. Edge Budget Execution (fail_closed)
- Missing `<budget_slice_remote_llm_calls>` auto-assigns the fallback of 10.
- Explicit `None` limits, `< 0` allocations, or illegal types yield immediate kernel block via `HTTP 403 Forbidden: {"ok": false, "error_code": "E_BUDGET_REJECTED"}`.

### 4. Idempotency Routing
- Telegram generic numerical IDs map securely to Executor strings:
  `idem_tg_<update_id>`

## Minimum Acceptance Criteria
Tests inside `tests/test_thread034_telegram_connector.py` comprehensively cover:
- Secret Webhook auth checks.
- Invalid schema and missing payload rejections.
- Complete array of 4 distinct Budget parameter states.
- Replay Mode null-action invocations.
