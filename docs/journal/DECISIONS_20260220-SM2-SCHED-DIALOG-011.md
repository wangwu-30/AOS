# DECISIONS: SM2 Scheduler × Dialog State Machine Link

- `thread_id`: `20260220-SM2-SCHED-DIALOG-011`
- `updated_at`: `2026-02-20`
- `status`: `accepted`

## Decision 001: Scheduler fire 写入 dialog 的 DIALOG_EVENT（不新增顶层字段）

- **状态**: `accepted`
- **结论**:
  - 采用 `policy_context["dialog_trace_id"]` 作为联动键（link key），将 scheduler fire/execute 事件写入对应 dialog trace。
  - 采用 `policy_context["trigger"]` 作为触发来源声明（trigger declaration），不升格为 ExecuteRequest 顶层字段。
  - Scheduler 在 dialog trace 中写入 `DIALOG_EVENT`：
    - `TURN_STARTED`（引用 fire_started evidence）
    - `TURN_FINISHED`（引用 fire evidence，并提供 `final_snapshot_ref` 指向该 evidence ref）

## Gate（必须通过的门禁）

1. 不破坏现有 CLI 稳定 JSON 输出字段集合（只新增 trace/evidence，不改 stdout schema）。
2. Remote API 依从性：不新增 ExecuteRequest 顶层字段；扩展点仅在 `policy_context`。
3. fail-closed 不降级：replay-mode 禁远程、double-gating 不降级（复用既有机制）。
4. rehydration 缺证据阻断：若 TURN_FINISHED 引用的 evidence meta 缺失，重建必须进入 `BLOCKED (missing_evidence)`。

## Acceptance（可验证验收）

- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_sm2_scheduler_dialog_link.py' -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`

## Evidence（证据）

- `docs/specs/MVP_015_SCHEDULER_DIALOG_LINK.md`
- `src/agentos_next/apps/scheduler_tick.py`
- `src/agentos_next/kernel/dialog_state_machine.py`
- `tests/test_spike_sm2_scheduler_dialog_link.py`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

