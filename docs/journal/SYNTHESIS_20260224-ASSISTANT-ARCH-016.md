# SYNTHESIS: Assistant App Reference Architecture (OpenClaw capability benchmark × ai-tutor architecture patterns)

- `thread_id`: `20260224-ASSISTANT-ARCH-016`
- `updated_at`: `2026-02-24`
- `status`: `accepted`
- `owner`: `human + codex`

## Summary（综合摘要）

本线程要解决的不是“要不要对标 OpenClaw”，而是：在既定能力 roadmap（THREAD-015: D/B/A）之下，个人助理应用层（assistant app layer）应采用何种参考架构，才能以最低风险保持 AgentOS Next 的核心不变量（fail-closed / replay / evidence-by-default / top-level API stable）。

## 当前共识（已确认）

- OpenClaw 仅作为**能力标杆（capability benchmark）**，用于定义“像样个人助理”的目标清单与验收指标，不作为架构蓝图。
- ai-tutor（main/dev_wjh_robot）提供可借鉴的应用层工程模式：显式状态机/权限边界、Progressive Disclosure、事件驱动、trace 可视化、Golden Trace 回归、插件化解耦。

## Round 1 输入状态（已齐）

- ext_gpt5_2：已提交（推荐 C/B/A：Hybrid / plugin P1 / GT P0；并代替 ext_gemini_flash 补齐 Remote/API 边界评审）
- ext_claude：已提交（C/B/A：Hybrid / plugin P1 / GT P0，从用户信任闭环角度）
- ext_gpt5_3：已提交（C/B/A：Hybrid / plugin P1 / GT P0；并给出最小 Hybrid 边界与 GT kill criteria）
- ext_gemini_flash：离线（不确定归期；Remote/API 边界评审已由 ext_gpt5_2 补齐）
- host：已提交（C/B/A 裁决倾向 + 北极星指标）

## Round 1 输入汇总

### 冲突 1：P0 runtime 形态

- A) Direct loop（传统主循环 + 直接调用 Orchestrator）
- B) Event-driven（事件驱动 runtime + 统一事件总线）
- C) Hybrid（事件驱动最小核 + 明确边界）

Round 1 已收到（ext_gpt5_2）：
- 主张：C（Hybrid）
- 提案 spike：Spike-ED1（event-driven core 最小闭环）

Round 1 已收到（ext_claude）：
- 主张：C（Hybrid），从"用户信任闭环"角度强调 event-driven 适合事件流治理，但需要保留 direct loop fallback
- 提案 spike：Spike-HY1（Hybrid runtime 最小闭环 + direct loop fallback）

Round 1 已收到（ext_gpt5_3）：
- 主张：C（Hybrid），并约束 event 类型集（5 类）+ single-leader/single-writer 语义
- 提案 spike：Spike-RT1（runtime bounded spike：最小 Hybrid 核 + direct fallback）

### 冲突 2：P0 plugin/hook system

- A) P0 引入（便于 channels/llm/memory/transport 解耦）
- B) P1 再引入（P0 保持简单）

Round 1 已收到（ext_gpt5_2）：
- 主张：B（P1 再引入）
- 提案 spike：Spike-PLUG0（可选 Transport plugin）

Round 1 已收到（ext_claude）：
- 主张：B（P1 再引入），从"用户信任闭环"角度强调插件化增加复杂度可能破坏可预测性
- 提案 spike：Spike-PLUG0（可选 P1）

Round 1 已收到（ext_gpt5_3）：
- 主张：B（P1 再引入），P0 先用稳定模块边界（channel adapter / planner / memory / scheduler）
- 提案 spike：Spike-PL0（plugin defer guard：用 adapter interface + 契约测试替代通用插件框架）

### 冲突 3：P0 Golden Trace/Golden Tests

- A) P0 引入最小 GT（可回放/可验收）
- B) P1 再引入

Round 1 已收到（ext_gpt5_2）：
- 主张：A（P0 引入）
- 提案 spike：Spike-GT1（3 条 GT：HITL 审批、soft-cancel、follow-up）

Round 1 已收到（ext_claude）：
- 主张：A（P0 引入），从"用户信任闭环"角度强调 GT 正是可回放/可审计的核心支撑
- 提案 spike：Spike-GT1（最小 Golden Trace）

Round 1 已收到（ext_gpt5_3）：
- 主张：A（P0 引入），并建议先落 3 条 Golden Trace：HITL_BLOCK / REPLAY_BLOCK / SCHED_FOLLOWUP_SUCCESS
- 提案 spike：Spike-GT1（golden trace bounded spike + flakiness kill criteria）

## Round 2 交叉评审汇总（ext_gpt5_2/ext_gpt5_3/ext_claude）

### strongest points（最强点）

- ext_claude：把“用户信任闭环（trust loop）”作为 P0 第一性原则，并要求 Hybrid 必保留 direct loop fallback（防止 event-driven 早期不稳定导致不可回放）。
- ext_gpt5_3：给出最小 Hybrid 边界（事件类型集 + single-writer），并把 kill criteria 绑定到顶层字段/幂等/replay 副作用（可执行）。
- gpt5_2(remote/api)：Remote/API 硬边界清晰（扩展仅 `policy_context`，由 PEP 统一校验，不动 `ExecuteRequest` 顶层），避免治理语义分叉。

### key risks（关键风险）

- Hybrid/direct 双路径漂移风险：成功路径一致但失败路径分叉（`idempotency_key` 派生、policy gate 顺序、error mapping、evidence/trace 结构）。
- Golden Trace 的 kill criteria 需量化：避免“表面通过、持续抖动（flaky）”。
- Transport/plugin 边界需明确：插件不得修改已校验的 `policy_context`（否则绕过 PEP）。

### 共识确认

- 冲突1（runtime）：三方均支持 C（Hybrid）✅
- 冲突2（plugin）：三方均支持 B（P1）✅
- 冲突3（GT）：三方均支持 A（P0）✅

### 建议硬前置（hard gates）

- Spike-HY2：Hybrid/direct 语义等价 harness（覆盖 HITL_BLOCK / REPLAY_BLOCK / SCHED_FOLLOWUP_SUCCESS / TOOL_FAIL 的稳定键等价断言）。
- Spike-GT2：Golden Trace 量化门禁（flakiness/稳定键/回放一致性）。
  - 建议口径（择一落盘即可）：
    - A) 连续 2 次失败触发回退（更“可操作”）
    - B) 连续 10 次回放全绿 + flake<=1%（更“可量化/更严格”）

## Round 3 综合建议（Recommendation Draft）

结论建议：进入 Round 4 裁决时，直接收口为 **C/B/A**，并把 HY2/GT2 作为“accepted 前置 gate”写入 DECISIONS（accept with conditions）。

## 裁决结果（Decision Outcome）

已裁决并收口为 **C/B/A**（见 `docs/journal/DECISIONS_20260224-ASSISTANT-ARCH-016.md`）。

实现分工：
- 实现：ext_gpt5_3
- Remote/API 守门与复核：ext_gpt5_2

### Evidence 评分矩阵（Security35 / Verifiability30 / Cost20 / Speed15）

> 说明：分数是相对评分，用于过 Decision Gate；不是“绝对真值”。

Decision001（runtime 形态）：
- A Direct loop：S=28 V=24 C=18 Sp=14 => **84**（安全分 < 30，不建议）
- B Event-driven full：S=30 V=27 C=10 Sp=8 => **75**（总分不足）
- C Hybrid minimal：S=32 V=28 C=15 Sp=12 => **87**（通过）

Decision002（plugin/hook）：
- A P0 引入：S=28 V=23 C=12 Sp=10 => **73**（不建议）
- B P1 引入：S=33 V=27 C=18 Sp=13 => **91**（通过）

Decision003（Golden Trace）：
- A P0 引入：S=34 V=30 C=14 Sp=10 => **88**（通过）
- B P1 引入：S=26 V=20 C=18 Sp=14 => **78**（不建议）

## Next

- 进入 Round 4（裁决）：在 `docs/journal/DECISIONS_20260224-ASSISTANT-ARCH-016.md` 选择 C/B/A，并把 HY2/GT2 作为 accepted 前置 gate 收口。
