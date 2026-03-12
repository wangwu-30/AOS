# DECISIONS: Spike-SCHED1 (Scheduler P0 Primitives)

- `thread_id`: `20260219-SCHED1-008`
- `updated_at`: `2026-02-19`
- `status`: `accepted`

## Decision 001: Scheduler P0 原语以 “builtin 创建 + 显式 tick runner 触发” 落地

- **状态**: `accepted`
- **结论**:
  - 对外提供 `builtin://scheduler.at` 与 `builtin://scheduler.cron` 创建任务并持久化；
  - 触发采用显式 runner（`mvp scheduler-tick` / `run_scheduler_tick_async`）驱动 due tasks；
  - 触发执行通过 `Orchestrator.execute(ExecuteRequest)` 复用既有 fail-closed、deadline、idempotency 与 evidence/trace 语义。

## Gate（必须通过的门禁）

- 不破坏现有契约（Non-breaking）：
  - 既有 CLI 子命令的稳定 JSON 输出字段集合不变（只允许新增子命令/新增字段）。
  - `docs/specs/EVIDENCE_TRACE.md` 既有 schema 不变（仅允许新增 evidence 内容类型/新增 trace event data 字段，不新增必填字段）。
- Fail-Closed 不降级：
  - replay-mode 下仍禁止任何远程调用；double-gating 不降级（复用既有机制，不新增绕过点）。
  - Scheduler 触发时对关键 policy keys（replay/remote_calls_armed/allow_network_egress/approved_by_human）必须强制覆盖或拒绝扩权。
- Deadline/幂等语义可验证：
  - `deadline_ms` <= 0 必须拒绝（timeout/rejected），且 tick 不可静默吞任务。
  - 重复 tick（同一 now）不会重复执行一次性任务（at）或同一 cron 窗口的重复触发。

## Acceptance（可验证验收）

- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_sched1_scheduler.py' -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`

## Evidence（证据）

- `docs/specs/MVP_012_SCHEDULER.md`
- `src/agentos_next/kernel/scheduler_store.py`
- `src/agentos_next/runtime/builtin_scheduler.py`
- `src/agentos_next/apps/scheduler_tick.py`
- `src/agentos_next/cli.py`
- `tests/test_spike_sched1_scheduler.py`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

