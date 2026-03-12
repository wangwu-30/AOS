# SYNTHESIS: SM2 Scheduler × Dialog State Machine Link

- `thread_id`: `20260220-SM2-SCHED-DIALOG-011`
- `updated_at`: `2026-02-20`
- `status`: `accepted`
- `owner`: `human + codex`

## Summary（综合摘要）

结论：采用“policy_context 扩展 + trace 追加事件”的最小联动方案，将 Scheduler 的后台触发执行纳入 Dialog State Machine（多轮状态机，Multi-turn Dialog State Machine）的可回放视图中。

关键共识（Consensus）：

- **不新增 ExecuteRequest 顶层字段**：trigger/dialog_link 仅通过 `policy_context` 透传，保持 Remote API 的 schema-first 与 forward-compatible 原则。
- **事件优先（event-first）**：Scheduler fire 时在目标 dialog trace 中追加 `event_type=DIALOG_EVENT` 的 `TURN_STARTED` 与 `TURN_FINISHED`，并通过 `evidence_refs` 引用 scheduler fire 的 evidence（避免“只写日志不写证据”的不可回放问题）。
- **fail-closed**：若 dialog_trace_id 缺失，则不写 dialog event（不伪造）；若写入的 evidence ref 缺失，则 rehydration 必须进入 `BLOCKED (missing_evidence)`。

## Evidence（证据）

- `docs/specs/MVP_015_SCHEDULER_DIALOG_LINK.md`
- `src/agentos_next/apps/scheduler_tick.py`
- `tests/test_spike_sm2_scheduler_dialog_link.py`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`（全量回归）

