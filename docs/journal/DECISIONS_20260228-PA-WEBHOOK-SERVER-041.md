# DECISIONS: THREAD-041 PA-WEBHOOK-SERVER

- `thread_id`: `20260228-PA-WEBHOOK-SERVER-041`
- `updated_at`: `2026-02-28`
- `status`: `accepted`

## Frozen Decisions

1. **top_level_api_stable**
   - 不新增 ExecuteRequest 顶层字段；只透传 `policy_context`（含 `memory_context`）。
2. **fail_closed**
   - 入站校验失败/服务异常/上下文编译失败必须稳定返回 error_code。
3. **replay_mode_no_side_effects**
   - replay-mode 严格 zero-write + no-network-side-effects。
4. **Loopback-only**
   - `mvp pa-webhook-server` 仅允许 loopback host 绑定。
5. **Budget freeze**
   - missing -> fallback=10；explicit null 或 invalid -> deny。
6. **MEM1 integration**
   - `memory_context_enabled=true` 且 C0/C1 引用无效时，返回 `E_PA_EV_CONTEXT_FAILED`。

## Acceptance

- `PYTHONPATH=src python3 -m unittest tests/test_thread041_pa_webhook_server.py -v`
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`
