# 2026-02-24 外部专家协作线程 016 (External Expert Collaboration Thread 016)

- `thread_id`: `20260224-ASSISTANT-ARCH-016`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-24`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

我们已明确：对标 OpenClaw 是**能力对标（capability benchmark）**，而不是要求复制 OpenClaw 的内部架构。现在需要进一步达成“择优选择（best-of-breed）”的工程共识：

- OpenClaw：作为个人助理能力上限/目标清单（channels/voice/canvas/长期常驻等）。
- ai-tutor（main/dev_wjh_robot）：作为“个人助理应用层（assistant app layer）”可借鉴的架构模式来源（事件驱动、插件化、Golden Trace、状态机/权限边界、Progressive Disclosure 等）。

本线程目标：在不破坏 AgentOS Next 内核不变量的前提下，选定 **P0 个人助理应用层（assistant app）** 的参考架构方案，并绑定 bounded spikes + 验收口径，供 host 最终裁决。

## 范围 (In Scope)

- 给出 2-3 个可执行的候选架构方案（OpenClaw-inspired / ai-tutor-inspired / Hybrid），并用统一指标对比。
- 为关键分歧提供 bounded spike + kill criteria，避免“无证据拍板”。
- 产出可验证 acceptance（命令级/测试级）。

## 非范围 (Out of Scope)

- 复制 OpenClaw 内部实现细节（我们不掌握其真实内部架构，也不以此为目标）。
- 把插件系统/事件总线下沉到 AgentOS Kernel（本线程仅讨论 assistant app layer；Kernel 仍以稳定与可审计为先）。

## 非协商约束 (Non-Negotiables)

- ExecuteRequest 顶层字段稳定（top-level API stable）；扩展点优先 `policy_context`。
- fail-closed 不降级；double gating 不降级。
- replay-mode 无新副作用（no new side effects），默认禁止远程副作用。
- evidence-by-default：关键路径必须可审计、可回放（trace/evidence on-disk schema stable）。

## 冲突与待裁决点 (Conflicts / Decision Points)

1. P0 assistant app runtime 形态：
  - A) 传统“主循环 + 直接调用 Orchestrator”的最小实现
  - B) 事件驱动（event-driven runtime）+ 统一事件总线（event bus）
  - C) Hybrid：事件驱动最小核 + 明确边界，插件化延后
2. P0 是否引入“插件化（plugin architecture）/hook system”：
  - A) P0 引入（便于 channels/llm/memory/transport 解耦）
  - B) P1 再引入（P0 保持简单）
3. P0 是否引入 Golden Trace/Golden Tests 作为稳定性主抓手：
  - A) P0 引入最小 GT（可回放/可验收）
  - B) P1 再引入

## 轮次进度 (Rounds)

- Round 0 (线程设定): 已完成
- Round 1 (独立提案): 已完成（ext_gpt5_2 / ext_claude / ext_gpt5_3 / host 已提交；ext_gemini_flash 离线，Remote/API 边界已由 ext_gpt5_2 代补齐）
- Round 2 (交叉评审): 已完成（ext_gpt5_2 / ext_claude / ext_gpt5_3）
- Round 3 (综合): 已完成（见 synthesis，推荐 C/B/A + HY2/GT2 gates）
- Round 4 (裁决): 已完成（见 decisions）

## Evidence (Links)

- `docs/specs/EXPERT_COLLAB_PROTOCOL.md`
- THREAD-015（能力对标的 roadmap 裁决 D/B/A）：
  - `docs/journal/DECISIONS_20260224-OPENCLAW-GAP-015.md`
  - `docs/journal/SYNTHESIS_20260224-OPENCLAW-GAP-015.md`
- ai-tutor（参考）：
  - `/Users/wangwu/.openclaw/workspace/ai-tutor/docs/architecture.md`
  - `/Users/wangwu/.openclaw/workspace/ai-tutor/docs/ai_native_architecture.md`
  - `git -C /Users/wangwu/.openclaw/workspace/ai-tutor show dev_wjh_robot:README.md`
  - `git -C /Users/wangwu/.openclaw/workspace/ai-tutor show dev_wjh_robot:PLUGIN_ARCHITECTURE.md`
  - `git -C /Users/wangwu/.openclaw/workspace/ai-tutor show dev_wjh_robot:EVENT_DRIVEN_QUICKSTART.md`
- 本线程产物：
  - `docs/journal/inputs/INPUT_ext_gpt5_2_assistant_arch_options.md`
  - `docs/journal/inputs/INPUT_ext_gpt5_2_assistant_arch_remote_api.md`
  - `docs/journal/inputs/INPUT_ext_gpt5_2_assistant_arch_cross_review.md`
  - `docs/journal/inputs/INPUT_ext_gpt5_3_assistant_arch_options.md`
  - `docs/journal/inputs/INPUT_ext_gpt5_3_assistant_arch_cross_review.md`
  - `docs/journal/inputs/INPUT_ext_claude_assistant_arch.md`
  - `docs/journal/inputs/INPUT_ext_claude_thread016_round2_cross_review.md`
  - `docs/journal/inputs/INPUT_host_assistant_arch.md`
  - `docs/journal/SYNTHESIS_20260224-ASSISTANT-ARCH-016.md`
  - `docs/journal/DECISIONS_20260224-ASSISTANT-ARCH-016.md`
