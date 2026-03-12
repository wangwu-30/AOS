# DECISIONS_20260228-THREAD-034

## Metadata
- **thread_id**: `20260228-EXT-COLLAB-034`
- **updated_at**: 2026-02-28T02:56:00Z
- **status**: resolved

## Final Frozen Decisions

1. **top_level_api_stable**: Telegram connector does not alter Core Types or Kernel capabilities.
2. **fail_closed** (Budget Governance):
   - Missing `budget_slice_remote_llm_calls` defaults to 10 natively to preserve P0 experience.
   - Explicit `None`, `< 0`, or illegal typing explicitly fails closed returning `403 Forbidden` (`E_BUDGET_REJECTED`).
3. **replay_mode_no_side_effects**: Replay mode execution actively halts core dispatch and skips all webhook/external network operations.
4. **Idempotency Routing**: 
   - Generates predictable key mappings of `idem_tg_{update_id}` per Telegram payloads.
5. **Security Gate**:
   - Immediate termination for failed tokens via HTTP 401 (`E_AUTH_FAILED`).
   - Try-Except encapsulation masks Python tracebacks into stable JSON `"E_CHANNEL_PAYLOAD_INVALID"` via HTTP 400.

## Acceptance Tests
- `PYTHONPATH=src:tests python3 -m unittest tests/test_thread034_telegram_connector.py -v`
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check`
