# SYNTHESIS: FU2 Follow-up Scheduling (Assistant loop × Scheduler)

- `thread_id`: `20260220-FU2-FOLLOWUP-SCHED-012`
- `updated_at`: `2026-02-20`
- `status`: `accepted`
- `owner`: `human + codex`

## Summary（综合摘要）

结论：采用“显式用户请求（CLI flag）+ Orchestrator 执行 scheduler.at + policy_context 注入 dialog_trace_id”的最小方案，把 FU1 的 plan-only follow-up 升级为可调度执行（schedulable execution），并保持：

- ExecuteRequest 顶层字段稳定（top-level API stable）
- forward-compatible：所有扩展仍在 `policy_context`
- replay-mode 下不产生新副作用（skip schedule, write evidence note）

关键点：

- 去重（Idempotency）：创建 follow-up 任务必须通过 Orchestrator 执行 `builtin://scheduler.at`，并使用稳定的 `idempotency_key`（基于 assistant loop root idempotency 派生），避免重复创建。
- 可回放（Replayable）：scheduler fire 的 dialog 事件由 SM2 写入 dialog trace；rehydration 缺证据进入 `BLOCKED`（已由 SM1/SM2 机制覆盖）。

## Evidence（证据）

- `docs/specs/MVP_016_FOLLOWUP_SCHEDULING.md`
- `src/agentos_next/apps/assistant_loop.py`
- `src/agentos_next/cli.py`
- `tests/test_spike_fu2_followup_scheduling.py`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`（全量回归）

