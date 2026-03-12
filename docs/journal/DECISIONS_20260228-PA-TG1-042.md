# DECISIONS: THREAD-042 PA-TG1 TaskGraph

- `thread_id`: `20260228-PA-TG1-042`
- `updated_at`: `2026-02-28`
- `status`: `accepted`

## Frozen Decisions

1. **top_level_api_stable**
   - 不新增 ExecuteRequest 顶层字段（扩展仅 policy_context）。
2. **fail_closed**
   - 循环检测/非法 schema/IO 异常必须稳定返回 error_code（无 traceback 泄漏）。
3. **replay_mode_no_side_effects**
   - replay-mode 下严格 zero-write（不创建目录/文件，不触发执行）。
4. **Task States**
   - 任务状态机至少包含：queued/running/succeeded/failed。
5. **Cycle Detection**
   - 同构 task fingerprint 重复触发必须 fail-closed：
     - `error_code = E_CYCLE_DETECTED`

## Acceptance

- `PYTHONPATH=src python3 -m unittest tests/test_thread042_pa_task_graph.py -v`
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check` => ok=true

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`
