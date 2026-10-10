# THREAD-034: Telegram Connector (PA-CH1) Implementation Plan

As defined by the host and reviewers, THREAD-034 focuses purely on the Telegram Channel Adapter implementation (`PA-CH1`).

## Pre-requisites (Envelope v0 Spec-Only)
Since THREAD-033 (EventEnvelope) is happening in parallel, this implementation assumes a stable, spec-only `EventEnvelope` defined as a frozen dataclass with `event_id` (used for `update_id` mapping) and `payload`.

## Proposed Changes

### Telegram Adapter Core

#### [NEW] [telegram_connector.py](file:///Users/wangwu/codex/agentos-next/src/agentos_next/apps/telegram_connector.py)
Create the HTTP Webhook entry point for Telegram.
- **Webhook Endpoint**: `POST /webhook/telegram`
- **Security Check (Kill Criteria 4)**: Must extract and verify `X-Telegram-Bot-Api-Secret-Token`. Any mismatch instantly returns `401 Unauthorized` without entering the kernel.
- **Idempotency Mapping (Kill Criteria 1)**: Maps `update_id` from the Telegram JSON to the `event_id` or `idempotency_key` of the Executor. Fallback to `message_id` within a specific chat context if `update_id` is somehow unstable (though Telegram guarantees `update_id` as unique).
- **Budget Seamless Integration (Kill Criteria 3)**: Must map incoming users to an active workspace/context, fetching budget bounds. Requests without corresponding budget slices must be rejected natively in the connector, avoiding non-budgeted kernel ingestion.
- **Error Stability (Kill Criteria 6)**: Try-except wrapper shielding standard Python tracebacks. Translates Telegram payload parsing failures or invalid schema structures strictly to static error representations (e.g. `E_CHANNEL_PAYLOAD_INVALID`) leading to an HTTP `400 Bad Request` or `500 Internal Server Error`, returning stable JSON `{ "error": "...", "code": "..." }`.

#### [NEW] [telegram_models.py](file:///Users/wangwu/codex/agentos-next/src/agentos_next/apps/telegram_models.py)
- Pydantic models (or strict frozen dataclasses) representing the structured `Update`, `Message`, `Chat`, and `User` payload structures.

---

### Tests

#### [NEW] [test_thread034_telegram_connector.py](file:///Users/wangwu/codex/agentos-next/tests/test_thread034_telegram_connector.py)
Covering the host and reviewer's strict requirements:
1. **test_verify_secret_token**: Asserts request without or with wrong token fails (Kill Criteria 4).
2. **test_idempotency_routing**: Validates extracting `update_id` correctly structures the incoming request's idempotency key.
3. **test_traceback_suppression**: Sends malformed JSON representing an update, ensuring stable `error_code` responses without raw Python traceback leakage.
4. **test_budget_rejection**: Tests an incoming call for a bot user lacking a valid budget context directly returning authorization denial.
5. **test_replay_protection**: (Requires THREAD-033 mock) Ensures the connector strictly respects routing with `replay_mode_no_side_effects`, firing no outbound network calls back to Telegram's REST API.

---

## Verification Plan

### Test Matrix (PA-CH1)
In accordance with `ext_gpt5_3`'s architecture gate requirements, the PA-CH1 test suite will implement the following strict matrix:

| Aspect | Condition | Expected Result | Kill Criteria Addressed |
| :--- | :--- | :--- | :--- |
| **Signature (Auth)** | Missing `X-Telegram-Bot-Api-Secret-Token` | `HTTP 401 Unauthorized`, Kernel zero-invocation | webhook 验签绕过 |
| **Signature (Auth)** | Invalid `X-Telegram-Bot-Api-Secret-Token` | `HTTP 401 Unauthorized`, Kernel zero-invocation | webhook 验签绕过 |
| **Signature (Auth)** | Valid `X-Telegram-Bot-Api-Secret-Token` | `HTTP 200/202`, Request accepted into Kernel | N/A |
| **Idempotency** | Webhook payload contains `update_id: 123` | `idempotency_key` mapped specifically to `idem_tg_123` | idem 漏拦截 (dedup) |
| **Budget/Scope** | Message from unregistered or out-of-budget user | `HTTP 403 Forbidden` / fail-closed, or route to fallback | Budget 接缝隐式无限制 |
| **Stability (Data)** | Malformed JSON or unexpected Telegram syntax | `HTTP 400 Bad Request`, Stable JSON error (No python tracebacks) | traceback 泄漏 |
| **Replay** | `replay_mode=True` simulation | No network outbound made back to Telegram API | replay 写盘 / 副作用 |

### Automated Tests
Run the standalone PA-CH1 unit-test suite locally (mocking out the Kernel/HTTP framework):
```bash
PYTHONPATH=src python3 -m unittest tests/test_thread034_telegram_connector.py -v
```

### Full Scope Testing
- Verify via `agentos_next.tools.thread_gate_check`
- Assert cross-thread compliance across 028-032 decisions.

### Kill Criteria Evaluation
Our test suite maps fundamentally one-to-one to the `PA-CH1` domain sections of the required global kill criteria.
