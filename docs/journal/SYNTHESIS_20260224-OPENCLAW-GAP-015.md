# SYNTHESIS: OpenClaw Gap → AgentOS Next Roadmap (个人助理差距与演进路线)

- `thread_id`: `20260224-OPENCLAW-GAP-015`
- `updated_at`: `2026-02-24`
- `status`: `accepted`

## 已知事实（Current State Facts）

- AgentOS Next 已具备 Kernel 级“可信执行（trusted execution）”基础：ASVP、fail-closed、evidence/trace 落盘、Orchestrator、LocalExecutor、Scheduler、Dialog State Machine、Registry、Memory、Assistant Loop。
- `Implementation Plan by gemini-3.1` 的 gap 分析主要指向上层能力：Planner/纠错循环、长期守护/事件触发、Browser/Computer Use、Rich UI、多通道接入、长期记忆（vector-like retrieval）。

## 架构不变量（Proposed Invariants）

1. ExecuteRequest 顶层字段稳定（top-level API stable）；扩展通过 `policy_context`。
2. replay-mode 无副作用；remote 默认禁止且双闸门不降级（double gating）。
3. evidence-by-default：关键动作都要可回放（trace）+ 可审计（evidence）。
4. 上层能力（Planner/UI/Channels/BrowserUse）优先以“可插拔技能（pluggable skills）/上层 App”实现，不下沉进 Kernel。

## 分歧与决策点（Conflicts / Decision Points）

### 冲突 1：OpenClaw 对标的 P0 先做什么？

- A) Channels-first：先做 Telegram/Discord 等多通道（interaction surface），让 OS loop 有真实入口。
- B) BrowserUse-first：先做浏览器/桌面自动化（computer use），快速扩展可用性。
- C) UI-first：先做 TUI/Web UI（可视化 + HITL），提升可用性与可审计性。

Round 1 已收到（ext_gpt5_3）：
- 主张：P0 选 Channels-first（但限定为"最小可审计通道闭环"），BrowserUse/UI-rich 放 P1。
- 提案 spike：Spike-CH1（单通道 ingress/egress + 去重幂等 + trace/evidence 贯通）。

Round 1 已收到（ext_claude）：
- 主张：P0 选 UI-first + Channels-embedded（不是纯 Channels-first），核心论点是"可审计 AI 助理"需要 HITL 审批流 + 可视化 trace 建立用户信任。
- 提案 spike：Spike-UI1（HITL 审批流 + 可视化 trace 最小闭环）+ Spike-DM2（daemon + 严格 admission gates）+ Spike-MEM-P0-ext（memory + 检索质量基线）。

Round 1 已收到（host）：
- 主张：倾向 P0 选 UI-first + Channels-embedded（先 TUI + local gateway；P1 再扩展 Telegram/Discord 与 BrowserUse）。
- 提案 spike：Spike-UI1（TUI/HITL + 可视化 trace）+ Spike-CH1（local gateway channel）+ Spike-DM2（daemon + WAL + single-writer）+ Spike-MEM-P0-ext（memory 基线）。

### 冲突 2：长期运行语义（daemon）是否进入 P0？

- A) 仍以显式 runner/tick 为主（deterministic runners），保持可回放。
- B) 引入常驻服务（daemon）+ 恢复语义（recovery），并新增更严格的 admission gates。

Round 1 已收到（ext_gpt5_3）：
- 主张：daemon 进 P0，但保留显式 runner/tick 作为 deterministic fallback。
- 提案 spike：Spike-DM1（常驻服务 + 重启恢复 + 单写者语义）。

Round 1 已收到（ext_claude）：
- 主张：daemon 进 P0，但需配套更严格的 admission gates（单写者语义 + 健康检查 + WAL 恢复 + 幂等调度），强调"治理优先于功能"。
- 提案 spike：Spike-DM2（单写者 + WAL + 健康检查 + 严格治理）。

Round 1 已收到（host）：
- 主张：daemon 进 P0，但保留显式 runner/tick 作为 deterministic fallback（回归/回放入口）。

### 冲突 3：长期记忆（vector retrieval）是否进入 P0？

- A) 继续 file-backed + naive search + compact 为主（可回放、成本低）。
- B) 引入向量检索（vector DB / embeddings），但必须严格约束隐私与成本（PII redaction + budget）。

Round 1 已收到（ext_gpt5_3）：
- 主张：file-backed/naive 进 P0，vector retrieval 进 P1。
- 提案 spike：Spike-MEM-P0（TTL/tombstone/compact + 分层索引 + 检索链 evidence，非向量）。

Round 1 已收到（ext_claude）：
- 主张：file-backed/naive 进 P0，vector retrieval 进 P1（与 ext_gpt5_3 一致），但强调 P0 需要定义检索质量基线（precision/recall baseline）。
- 提案 spike：Spike-MEM-P0-ext（TTL/tombstone/compact + 分层索引 + 检索链 evidence + precision/recall 基线测量）。

Round 1 已收到（host）：
- 主张：file-backed/naive 进 P0，vector retrieval 进 P1（需配套 PII redaction + budget gates）。

## 综合建议（Synthesis Recommendation）

基于目前输入，建议将三个冲突收敛为以下裁决倾向（供 Round 4 裁决/DECISIONS 落盘）：

1. Decision001（P0 优先级）：选 **D) UI-first + Channels-embedded**
  - 先做最小 TUI/Web UI 之一（建议先 TUI）+ local gateway channel，把 HITL/trace/evidence 变成用户可感知闭环。
  - P1 再扩展 Telegram/Discord 与 BrowserUse（高风险能力）。
2. Decision002（daemon）：选 **B) daemon 进 P0 + 保留 runner/tick fallback**
  - 单机 single-writer + WAL + health/heartbeat，且保留 `scheduler-tick`/runner 作为可回放入口。
3. Decision003（memory）：选 **A) file-backed/naive 进 P0，vector retrieval 进 P1**
  - P0 聚焦治理与可回放；P1 以 bounded spike 引入向量检索与预算/脱敏门禁。

## 裁决结果（Decision Outcome）

Host 已裁决并收口为 **D/B/A**（见 `docs/journal/DECISIONS_20260224-OPENCLAW-GAP-015.md`）：

1. Decision001: **D) UI-first + Channels-embedded**
2. Decision002: **B) daemon 进 P0 + runner/tick fallback**
3. Decision003: **A) file-backed/naive memory 进 P0；vector retrieval 进 P1**

## 为什么“对标 OpenClaw”不是“照抄 OpenClaw 架构”

- OpenClaw 在本线程的定位是**产品能力标杆（capability benchmark）**，用于定义“个人助理像样”的可验证指标与差距清单（见 `agentos-next/Implementation Plan by gemini-3.1`），不是要求复制其内部架构。
- AgentOS Next 的核心不变量是**可信执行（trusted execution）**与**可审计/可回放（auditable + replayable）**；因此路线选择会优先保证 HITL + trace/evidence 闭环、fail-closed 与 replay-mode 无副作用，而不是追求“功能堆叠的最快速度”。

## 参考项目：ai-tutor（main / dev_wjh_robot）

ai-tutor 更像“产品级 agent 应用（agent app）”，但有不少值得借鉴到 AgentOS Next 上层 App/Skills 的架构模式：

- **动态 Prompt 生成器（prompt generator）**与**按需加载技能（Progressive Disclosure）**：把“索引层 vs 重内容层”的技能组织方式前置，降低 token 成本与上下文噪音（见 `/Users/wangwu/.openclaw/workspace/ai-tutor/docs/ai_native_architecture.md`）。
- **显式状态机（state machine）+ 权限边界（permission boundaries）**：把“允许监控/提醒”的能力限制在特定状态内，并要求用户协商同意，天然契合 HITL（见 `/Users/wangwu/.openclaw/workspace/ai-tutor/docs/architecture.md`）。
- **本地优先记忆 + 调度 + 黑名单双闸门（local-first memory + scheduler + blacklist double gating）**：对应我们 P0 memory/scheduler 的治理方向（见 `/Users/wangwu/.openclaw/workspace/ai-tutor/docs/memory_scheduler_model.md`）。
- dev_wjh_robot 分支额外强调：**事件驱动（event-driven）**、**插件化（plugin architecture）**、**trace 可视化（trace visualizer）**与**Golden Trace 回归**，对我们 P0 的 daemon/UI/HITL 收敛路径有直接启发。
- 补充输入（归档）：`docs/journal/inputs/INPUT_ext_gpt5_2_ai_tutor_reference.md`

## 建议的限界实验（Bounded Spikes, draft）

- Spike-PA1（P0 候选）：Channel adapter + HITL 最小闭环（把消息→ExecuteRequest→Evidence/Trace→HITL 决策串起来）。
  - kill criteria：任何 replay-mode 产生副作用或任何越权远程调用。
- Spike-BU1（P0 候选）：BrowserUse skill（Playwright/Accessibility API）最小 demo，强制录制可回放 evidence。
  - kill criteria：无法在本地 deterministic 回放/稳定复现（导致审计不可用）。

## 下一步（Next）

- 进入 Round 4（裁决）：在 `DECISIONS_20260224-OPENCLAW-GAP-015.md` 选择 Decision001/002/003 的最终口径，并为 P0 spikes 绑定 acceptance + kill criteria。
