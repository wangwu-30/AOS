# DECISIONS: Assistant App Reference Architecture (best-of-breed selection)

- `thread_id`: `20260224-ASSISTANT-ARCH-016`
- `updated_at`: `2026-02-24`
- `status`: `accepted`

## Decision 001: P0 assistant app runtime 形态

- **状态**: `accepted`
- **候选结论**:
  - A) 最小主循环（direct loop）：App 内直接驱动 assistant loop，调用 Orchestrator 执行 Skills；少抽象，先交付。
  - B) 事件驱动（event-driven）：统一 EventBus（input/trigger/tool_result/followup），以事件→任务→执行的方式推进。
  - C) Hybrid：事件驱动最小核（event bus + single-leader），但不引入完整插件系统；先把 UI/HITL/Channels/Daemon 跑通。
- **推荐结论（proposal）**: 选 **C) Hybrid**
  - 补充条件（accept with conditions）：
    - 必须先完成 Spike-HY2（Hybrid/direct fallback 语义等价 harness），覆盖失败路径等价（避免双路径漂移）。

## Decision 002: P0 是否引入插件化（plugin architecture / hook system）

- **状态**: `accepted`
- **候选结论**:
  - A) P0 引入：便于 LLM/Memory/Transport/Tools/Channels 以插件替换与隔离。
  - B) P1 引入：P0 保持简单边界，先用显式模块与稳定接口，避免平台化过早抽象。
- **推荐结论（proposal）**: 选 **B) P1 引入**
  - 补充条件：
    - 若做 Spike-PLUG0/PL0（仅 Transport adapter/plugin），必须明确 kill criteria：插件不得修改已校验的 `policy_context`（避免绕过 PEP）。

## Decision 003: P0 是否引入 Golden Trace/Golden Tests

- **状态**: `accepted`
- **候选结论**:
  - A) P0 引入最小 GT：以可回放 trace + 断言作为“回归主抓手”，绑定 UI/HITL/daemon 的关键闭环。
  - B) P1 引入：P0 只做常规单测/集成测。
- **推荐结论（proposal）**: 选 **A) P0 引入**
  - 补充条件（accept with conditions）：
    - 必须先完成 Spike-GT2（量化门禁）：明确 flakiness/稳定键/回放一致性的硬阈值与回退触发条件。

## Gate（进入 accepted 前必须通过的门禁）

1. 不新增 ExecuteRequest 顶层字段（扩展优先 policy_context）。
2. fail-closed / replay-mode / evidence-by-default 不降级。
3. 任一候选结论若涉及高风险抽象（plugin/event bus），必须先给 bounded spike + kill criteria。
4. Spike-HY2 + Spike-GT2 已完成（见 THREAD-017/018），用于避免双路径漂移 + GT 抖动不可控。

## Implementation Owner（实现负责人）

- 实现：`ext_gpt5_3`
- Remote/API 守门与复核：`ext_gpt5_2`（policy_context only / no top-level API expansion / replay+double-gating invariants）

## 单一硬回退阈值（One Hard Rollback Trigger）

- 一旦出现 replay-mode 下任何新副作用（写盘/远程/不可回放），立即回退并阻断合并（fail-closed）。

## Acceptance（可验证验收）

- 本线程三件套存在：
  - `docs/journal/2026-02-24-expert-collab-thread-016.md`
  - `docs/journal/SYNTHESIS_20260224-ASSISTANT-ARCH-016.md`
  - `docs/journal/DECISIONS_20260224-ASSISTANT-ARCH-016.md`
- Gate 交付线程存在：
  - `docs/journal/2026-02-24-expert-collab-thread-017.md`
  - `docs/journal/2026-02-24-expert-collab-thread-018.md`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

