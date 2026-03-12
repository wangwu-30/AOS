# DECISIONS: FU2 Follow-up Scheduling (Assistant loop × Scheduler)

- `thread_id`: `20260220-FU2-FOLLOWUP-SCHED-012`
- `updated_at`: `2026-02-20`
- `status`: `accepted`

## Decision 001: FU2 采用显式 flag 调度（Orchestrator->scheduler.at），replay-mode skip

- **状态**: `accepted`
- **结论**:
  - `mvp assistant-loop`/`mvp assistant-loop-stdio` 提供 `--followup-at <UTC ISO>`，仅在用户显式提供时调度 follow-up。
  - 调度通过 Orchestrator 执行 `builtin://scheduler.at` 创建任务，并用稳定 `idempotency_key` 去重。
  - 任务 `execute_request.policy_context` MUST 注入 `dialog_trace_id=<session trace_id>` 以便 SM2 写入 dialog 的 `DIALOG_EVENT`。
  - `replay_mode=true` 时 MUST 不创建任务（no new side effects），但写 evidence note（policy）。

## Gate（必须通过的门禁）

1. 不破坏既有 CLI 稳定 JSON 输出字段集合（仅新增 flag、追加 evidence/trace）。
2. ExecuteRequest 顶层字段稳定；扩展仅走 `policy_context`。
3. fail-closed 不降级：replay-mode 禁远程；double-gating 不降级。
4. 调度创建必须通过 Orchestrator（利用 idempotency_store 避免重复）。

## Acceptance（可验证验收）

- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_fu2_followup_scheduling.py' -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`

## Evidence（证据）

- `docs/specs/MVP_016_FOLLOWUP_SCHEDULING.md`
- `src/agentos_next/apps/assistant_loop.py`
- `src/agentos_next/cli.py`
- `tests/test_spike_fu2_followup_scheduling.py`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

