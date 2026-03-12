# MVP-016 Follow-up 调度执行（Follow-up Scheduling Execution）

- 状态（Status）：Draft
- 日期（Date）：2026-02-20
- 目标 Spike（Target Spike）：FU2（Assistant loop × Scheduler follow-up）
- 相关规范（Related Specs）：
  - `docs/specs/MVP_011_ASSISTANT_LOOP.md`（assistant loop + FU1 plan-only）
  - `docs/specs/MVP_012_SCHEDULER.md`（scheduler.at + scheduler-tick）
  - `docs/specs/MVP_015_SCHEDULER_DIALOG_LINK.md`（SM2：dialog_trace_id + trigger）
  - `docs/specs/MVP_014_DIALOG_STATE_MACHINE.md`（rehydration / BLOCKED）
  - `docs/specs/LLM_PROVIDER.md`（replay-mode + double-gating）

## 1. 目的（Purpose）

把 FU1 的 plan-only follow-up 升级为“可调度执行（schedulable execution）”，从而支持最小的 OS 循环（OS loop）：

- 用户显式请求：`--followup-at <UTC ISO>`
- assistant loop 创建 scheduler.at 任务
- scheduler-tick 到期触发执行
- 结果进入 evidence/trace，并可被 dialog rehydration 回放

## 2. 核心原则（Principles）

1. 显式触发（explicit user intent）：只在用户明确提供 `--followup-at` 时调度，默认不产生后台副作用。
2. 去重（idempotency）：创建任务必须通过 Orchestrator 执行 `builtin://scheduler.at`，并使用稳定 `idempotency_key`。
3. forward-compatible：不新增 ExecuteRequest 顶层字段；所有联动键位通过 `policy_context`（dialog_trace_id/trigger）。
4. replay-mode 无副作用：`replay_mode=true` MUST skip 调度创建，但写 evidence note（policy）。

## 3. CLI（接口）

### 3.1 mvp assistant-loop

新增参数（SHOULD）：
- `--followup-at <UTC ISO>`（optional）

### 3.2 mvp assistant-loop-stdio

新增参数（SHOULD）：
- `--followup-at <UTC ISO>`（optional）

## 4. 调度语义（Scheduling Semantics）

当满足：
- `followup_at` 存在
- assistant loop `ok=true`
- `replay_mode=false`

则必须创建 scheduler.at 任务，其 execute_request 草案最小字段：

- `skill_ref`: 复用本次 assistant loop 的 `assistant_skill_dir`（或 default example）
- `input`: `{"request": "[Follow-up] <original query>"}`
- `deadline_ms`: bounded（建议 3000-10000ms）
- `policy_context` MUST 包含：
  - `verify_asvp/public_keys_dir/backend/model`（与本次一致）
  - `dialog_trace_id=<session trace_id>`（用于 SM2 写入 dialog 事件）

## 5. Acceptance（验收）

- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_fu2_followup_scheduling.py' -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`

