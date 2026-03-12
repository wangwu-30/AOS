# DECISIONS: THREAD-044 PA-POLLING

- `thread_id`: `20260228-PA-POLLING-044`
- `updated_at`: `2026-02-28`
- `status`: `accepted`

## Frozen Decisions

1. **top_level_api_stable**
   - 不新增 ExecuteRequest 顶层字段；只透传 `policy_context`。
2. **fail_closed**
   - 轮询失败、payload 非法、执行失败必须返回稳定 `error_code`。
3. **replay_mode_no_side_effects**
   - replay-mode 下不写入 `pa/events|outbox|dedup` 且不发送 reply。
4. **Ingress form**
   - 使用 Telegram `getUpdates` 本地轮询，不依赖公网 webhook。
5. **Dedup invariant**
   - 同一 `update_id` 重放只允许一次 reply。

## Acceptance

- `PYTHONPATH=src python3 -m unittest tests/test_thread044_pa_polling.py -v`
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`
