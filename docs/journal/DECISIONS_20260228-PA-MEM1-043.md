# DECISIONS: THREAD-043 PA-MEM1（Progressive Context Pipeline）

- `thread_id`: `20260228-PA-MEM1-043`
- `updated_at`: `2026-02-28`
- `status`: `accepted`

## Frozen Decisions

1. **top_level_api_stable**
   - 不新增 ExecuteRequest 顶层字段；上下文扩展仅 `policy_context["memory_context"]`。
2. **fail_closed**
   - PA-MEM1 构建失败必须拒绝执行：`E_PA_EV_CONTEXT_FAILED`。
3. **replay_mode_no_side_effects**
   - replay-mode 下不得新增 evidence/trace 写入。
4. **Context Contract**
   - `memory_context` 必含：`schema_version/l0_session_inline/l1_short_refs/l2_long_query/selection_trace`。
5. **Enablement**
   - `memory_context_enabled` 默认 `false`，仅显式打开时生效。

## Acceptance

- `PYTHONPATH=src python3 -m unittest tests/test_thread043_pa_mem1_pipeline.py -v`
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check` => ok=true

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`
