# MVP-015 Scheduler × 多轮状态机联动（Scheduler × Dialog State Machine Link）

- 状态（Status）：Draft
- 日期（Date）：2026-02-20
- 目标 Spike（Target Spike）：SM2（Scheduler × State Machine）
- 相关规范（Related Specs）：
  - `docs/specs/MVP_012_SCHEDULER.md`（Scheduler primitives）
  - `docs/specs/MVP_014_DIALOG_STATE_MACHINE.md`（Dialog state machine）
  - `docs/specs/EVIDENCE_TRACE.md`（Evidence/Trace）
  - `docs/specs/REMOTE_SANDBOX_API.md`（policy_context 前向兼容）
  - `docs/specs/LLM_PROVIDER.md`（replay-mode + double-gating）

## 1. 目的（Purpose）

让 Scheduler 触发的后台执行（background fire/execute）进入 Dialog State Machine 的可回放视图（dialog lifecycle view），用于支持 “提醒/跟进（follow-up）” 这类 OS 级闭环能力：

- 审计：能从 dialog trace 看到 “某个后台任务被触发并执行了什么”
- 回放：缺证据时 fail-closed 进入 BLOCKED，而不是 silent skip

## 2. 核心原则（Principles）

1. 不新增 ExecuteRequest 顶层字段：trigger/dialog link MUST 放在 `policy_context`（forward-compatible）。
2. 事件优先：通过 `TraceEvent.event_type=DIALOG_EVENT` 追加事件，保持 append-only。
3. Evidence by default：dialog event MUST 通过 `evidence_refs` 引用 scheduler fire evidence（可回放）。
4. fail-closed：引用 evidence 缺失时，rehydration 必须进入 `BLOCKED (missing_evidence)`。

## 3. Data Contract（数据契约）

### 3.1 policy_context 扩展点（MUST）

- `policy_context["dialog_trace_id"]`（string, optional）
  - 当存在时，表示本次 scheduler fire 应写入/关联到该 dialog trace（dialog_id=trace_id）。
- `policy_context["trigger"]`（object, optional）
  - 触发来源声明（trigger declaration），示例：
    ```json
    {
      "type": "scheduler",
      "task_id": "sched_...",
      "kind": "at|cron",
      "fired_at": "UTC ISO"
    }
    ```

> 注：在出现 “Kernel-Level Governance & Quota Enforcement（内核级治理与配额拦截）” 硬需求前，不支持将 trigger 升格为 ExecuteRequest 顶层字段。

### 3.2 DIALOG_EVENT（MUST）

当 `dialog_trace_id` 存在时，Scheduler tick MUST 追加以下 dialog 事件到 `data/traces/<dialog_trace_id>.jsonl`：

1. `TURN_STARTED`
  - `data.dialog_event_type="TURN_STARTED"`
  - `data.dialog_id=<dialog_trace_id>`
  - evidence：`evidence_refs` MUST 包含一个 `fire_started` evidence ref（kind=routing 或 snapshot）
2. `TURN_FINISHED`
  - `data.dialog_event_type="TURN_FINISHED"`
  - `data.dialog_id=<dialog_trace_id>`
  - `data.ok` / `data.error_code`
  - `data.final_snapshot_ref` MUST 指向 scheduler fire evidence ref
  - evidence：`evidence_refs` MUST 包含 scheduler fire evidence ref

## 4. Acceptance（验收）

必须（MUST）：

- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_sm2_scheduler_dialog_link.py' -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`

