# PA-CH1 & PA-EV1 Integration Checklist

## Field Mapping (PA-CH1 -> PA-EV1 Envelope v0)
1. **`event_id`**: `tg_update_{update_id}`
2. **`idempotency_key` (Adapter Layer)**: `idem_tg_{update_id}`
3. **`source`**: `"telegram"`
4. **`received_at_utc`**: `datetime.now(timezone.utc).isoformat()`
5. **`workspace_id`**: Mapped directly from registered bot/tenant configs.
6. **`conversation_id`**: `str(update.message.chat.id)`
7. **`sender_id`**: `str(update.message.from_user.id)` (Unknown if missing)
8. **`message_text`**: `update.message.text`
9. **`budget_slice_remote_llm_calls`**: 
   - `int >= 0` (passed normally).
   - Missing explicitly translates to `10`.
   - `None` or Illegal immediately halts with `HTTP 403`, zero kernel traversal.

## Error Code Mapping
- `E_AUTH_FAILED` (HTTP 401)
- `E_CHANNEL_PAYLOAD_INVALID` (HTTP 400)
- `E_BUDGET_REJECTED` (HTTP 403)
- Ev1 mapping bounds: `E_PA_EV_SCHEMA_INVALID`, `E_PA_EV_REPLAY_DENY`, `E_PA_EV_IO_FAILED`.

## End-to-End Test Verification Cases
1. **Standard Ingestion & Idempotency Drop**
   A standard webhook is fired into `PA-CH1` yielding `idem_tg_100` and `event_id_100`. The PA-EV1 pipeline should generate an append-only log, routing this to the ExecuteRequest. A duplicated inbound of `idem_tg_100` should cleanly hit `PA-EV1`'s dedup cache, resulting in zero outbound side-effects and immediately returning the identical Outbox JSON value from prior without re-executing.
2. **Replay Mode Strict Zero Network/Disk Hit**
   Webhook is fired with `replay_mode=True`. `PA-CH1` safely skips dispatcher routing. During broader `PA-EV1` tests invoking `ExecuteRequest(replay_mode=True)`, `PA-EV1` must not append to EventLogs, Outbox records, or Metering lines.
