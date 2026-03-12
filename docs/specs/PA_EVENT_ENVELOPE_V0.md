# PA_EVENT_ENVELOPE_V0

## Scope

Shared V0 contract for Personal Assistant application layer components:

- THREAD-033: PA-EV1 (EventEnvelope/EventLog/Outbox/Dedup)
- THREAD-034: PA-CH1 (Telegram Connector)
- THREAD-035: PA-MTR0 (Metering evidence v0)

This is an application-layer schema. It must **not** expand `ExecuteRequest` top-level fields.

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

## EventEnvelopeV0 (Stable JSON)

### Required (MUST)

- `schema_version`: `"1.0.0"`
- `event_id`: `string` (REQUIRED)
- `idempotency_key`: `string` (REQUIRED)
- `source`: `string` (v0: `"telegram"`)
- `received_at_utc`: `string` (UTC ISO)
- `workspace_id`: `string` (project/tenant isolation boundary)
- `conversation_id`: `string` (e.g. Telegram chat_id)
- `sender_id`: `string` (e.g. Telegram from.id)
- `message_text`: `string`
- `budget_slice_remote_llm_calls`: `int >= 0`

### Optional (SHOULD/MAY, forward-compatible)

- `policy_context_passthrough`: `object`
  - MUST NOT grant privileges by itself
  - EV1 may merge it into `ExecuteRequest.policy_context` as a pure passthrough

## Budget Freeze (THREAD-034)

For Telegram ingress:

1. field missing (`budget_slice_remote_llm_calls` not provided by caller) -> fallback `10`
2. field explicit `null` -> fail-closed (deny)
3. field invalid (non-int or <0) -> fail-closed (deny)
4. field valid `int>=0` -> enforce as-is

Note: enforcement is performed by Kernel THREAD-029 Budget v1 when remote LLM is armed.

## Idempotency & Dedup (THREAD-033)

- EV1 MUST validate `event_id` and `idempotency_key` are present; EV1 MUST NOT infer defaults.
- Dedup key: `event_id`
  - If `event_id` already has an outbox result, EV1 MUST short-circuit and return the stored outbox without re-executing.
- `idempotency_key` is passed through to `ExecuteRequest.idempotency_key` (Kernel idempotency store).

## Replay Mode

EV1/MTR0 replay-mode is strict:

- zero-write (no pa/events, pa/outbox, pa/dedup, metering evidence)
- no remote side effects
- stable error code for deny

