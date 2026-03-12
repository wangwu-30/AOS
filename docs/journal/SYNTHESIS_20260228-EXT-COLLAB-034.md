# SYNTHESIS_20260228-THREAD-034

## Topic
PA-CH1 Telegram Webhook Integration & Gateway Governance.

## Context
The PA-CH1 integration acts as an untrusted boundary. Strict checks are required to convert inbound webhook updates into `EventEnvelopeV0` types securely.

## Identified Points
1. **Signature Security**: Reject if `X-Telegram-Bot-Api-Secret-Token` does not match the internal expected token natively before accessing the core pipeline (`401 Unauthorized`).
2. **Idempotency Strategy**: The generic `update_id` must be explicitly prefixed and routed as `idem_tg_{update_id}` into the orchestrator.
3. **Replay Mode Guarantee**: Zero network writes and Zero disk writes.

## Resolution on Budget Conflicts
A severe conflict arose regarding `budget_slice_remote_llm_calls`:
- Missing entirely: Assign `fallback=10` limits.
- Explicitly `null` sent by source: HTTP `403 Forbidden` (`fail-closed`).
- Object type illegal (strings / negative int): HTTP `403 Forbidden` (`fail-closed`).

## Next Actions
Proceed with `DECISIONS` documentation and enforce through the thread gate checks.
