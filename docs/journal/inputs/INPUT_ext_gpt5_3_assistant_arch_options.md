id: `20260224-ext_gpt5_3-assistant-arch-001`
author: `ext_gpt5_3`
topic: `THREAD-016 Round 1：个人助理应用层参考架构择优（runtime/plugin/golden-trace）`
position:
- Decision001（P0 runtime 形态）：我支持 `C) Hybrid`。P0 采用“事件驱动最小核（event-driven minimal core）+ 单写者（single-leader）+ 显式边界”，不做完整平台化总线。
- Decision002（P0 plugin/hook）：我支持 `B) P1 引入`。P0 先用稳定模块边界（channel adapter / planner / memory / scheduler），避免过早抽象导致排障与回放复杂度上升。
- Decision003（P0 Golden Trace/Golden Tests）：我支持 `A) P0 引入`。这是保证 UI/HITL/daemon/channels 不回归的最低成本硬约束。
- 最小可行 Hybrid 边界（MVP 边界）：
  - 仅允许 5 类事件：`USER_INPUT` / `SCHED_TRIGGER` / `STEP_DONE` / `POLICY_BLOCKED` / `OUTPUT_READY`
  - 仅一个执行管线拥有写权限（single-writer），其他组件只发事件不落状态
  - 所有跨模块扩展一律走 `policy_context`，不改 `ExecuteRequest` 顶层
evidence:
- `docs/specs/MVP_011_ASSISTANT_LOOP.md`
- `docs/specs/MVP_012_SCHEDULER.md`
- `docs/specs/MVP_014_DIALOG_STATE_MACHINE.md`
- `docs/specs/EVIDENCE_TRACE.md`
- `docs/specs/EXECUTOR_API.md`
- `docs/journal/DECISIONS_20260224-OPENCLAW-GAP-015.md`（D/B/A 能力路线）
- `src/agentos_next/apps/assistant_loop.py`
- `src/agentos_next/apps/scheduler_tick.py`
- `src/agentos_next/kernel/orchestrator.py`
tradeoffs:
- Hybrid（Decision001-C）：
  - 收益：兼顾交付速度与治理；对 daemon/channels/follow-up 更自然；可保留 deterministic 回放入口
  - 风险：若事件类型失控会演化为隐式复杂系统
- 插件延后（Decision002-B）：
  - 收益：P0 复杂度可控、排障链路短、契约稳定
  - 风险：短期可替换性与生态接入速度一般
- Golden Trace 先行（Decision003-A）：
  - 收益：把“可回放/可审计”从口号变成门禁
  - 风险：首轮需要投入基线样本与断言维护
open_questions:
- P0 是否需要在 `OUTPUT_READY` 里固定最小 UI 渲染字段（例如 `ui_intent` / `approval_state`）作为前端契约？
- Golden Trace 的“稳定键集合”如何定义为可演进（新增字段可放宽、既有字段不可删）？
proposal:
- Spike-RT1（runtime，bounded）：
  - 实现最小 Hybrid 核 + 5 事件类型 + single-leader dispatcher
  - 保留显式 `runner/tick` 入口作为回放与回归入口
  - kill criteria：
    - 需要新增 `ExecuteRequest` 顶层字段才能继续；
    - replay-mode 出现任何副作用（写盘/远程）；
    - 同一输入产生重复执行且无法被 idempotency 吸收
- Spike-PL0（plugin defer guard，bounded）：
  - P0 不引入通用插件框架，只定义 adapter interface（transport/planner）与契约测试
  - kill criteria：
    - 为支持第二个通道必须复制 >30% glue code；
    - adapter 层无法承载 policy gate（double gating）而需侵入核心
- Spike-GT1（golden trace，bounded）：
  - 先落 3 条 Golden Trace：`HITL_BLOCK` / `REPLAY_BLOCK` / `SCHED_FOLLOWUP_SUCCESS`
  - 每条都校验：事件序列、关键 evidence_refs、稳定 error_code
  - kill criteria：
    - Golden 在非语义改动下每周抖动 >2 次；
    - 为维持 Golden 需要放宽 fail-closed 或删除关键 evidence 字段
acceptance:
- 本输入文件存在：`docs/journal/inputs/INPUT_ext_gpt5_3_assistant_arch_options.md`
- THREAD-016 决策可进入 Round 2 的最低条件：
  - 对 Decision001/002/003 均有明确 stance；
  - 每个 stance 提供 bounded spike + kill criteria；
  - 明确不变量：`ExecuteRequest` 顶层稳定、fail-closed/double-gating/replay 不降级
- 回归门：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
confidence: `high`
