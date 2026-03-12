# 2026-02-19 外部专家协作线程 004 (External Expert Collaboration Thread 004)

- `thread_id`: `20260219-ASSISTANT-LOOP-004`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-19`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

在 AgentOS Next 现有 `Orchestrator -> Executor` 执行骨架之上，定义并落地一条“assistant loop”（多步执行 + tool-calling + 可审计 trace/evidence）的最小闭环，并以限界实验（Bounded Spike）方式验证其可行性与安全边界。

该议题由 OpenCLAW 助手能力线程中的 “Follow-up/主动跟进循环” 引出，并由外部专家明确建议下一步执行 “assistant loop 的 bounded spike”。（见 Evidence）

## 范围 (In Scope)

- 定义 Spike-AL1 的最小目标、非目标、可交付产物（Artifacts）。
- 明确 assistant loop 的边界条件：boundedness（step/time/budget）、fail-closed、安全闸门、回放（replay）语义。
- 给出可执行的 gate/acceptance（用于实现 PR 的验收口径）。

## 非范围 (Out of Scope)

- 不在本线程直接实现真实 LLM Provider、真实远程 sandbox 调用或生产级对话 UI。
- 不引入新的外部网络能力；远程执行能力仍遵循既有 Remote API / replay-mode 安全策略。

## 非协商约束 (Non-Negotiables)

- 默认 fail-closed 不得被削弱（尤其是 replay-mode、远程调用双闸门、无 stack trace 泄露）。
- 不得破坏既有 CLI 稳定 JSON 输出与 evidence/trace 落盘 schema。
- assistant loop 必须是 bounded（至少包含 `max_steps` 与 `deadline_ms` 的硬上限）。

## 轮次进度 (Rounds)

- Round 0 (线程设定): 完成
- Round 1 (独立提案): 完成（见 inputs）
- Round 2 (交叉评审): 完成（见 inputs）
- Round 3 (综合): 完成（见 synthesis）
- Round 4 (裁决): 完成（见 decisions）

## 消息记录 (Message Log)

- ext_claude: 提议下一步执行 “assistant loop bounded spike”（来源为 MVP-010 架构防线确认后的 next step）
- host_codex: 提供 Spike-AL1 的边界、门禁与验收口径（对齐既有 Orchestrator/Executor/trace/evidence 不变量）

## Evidence (Links)

- `docs/journal/inputs/INPUT_ext_claude_bus_mvp010_007.md`（legacy note: “接入 assistant loop 的 bounded spike”）
- `docs/journal/inputs/INPUT_ext_claude_assistant_loop_al1.md`
- `docs/journal/inputs/INPUT_host_codex_assistant_loop_al1.md`
- `docs/journal/2026-02-19-expert-collab-thread-003.md`（OpenCLAW Assistant thread: Follow-up/主动循环是 P0 能力）

## Addendum（追加）：AL1 当前落地与边界澄清

- AL1 仅验证 “deterministic 计划 + 多步工具执行 + trace/evidence 落盘” 的最小闭环；不包含真实 LLM provider 集成或动态 tool-calling 规划。
- boundedness 在 AL1 允许采用“固定有限步数”实现（与显式 `max_steps` 等价），并通过 `deadline_ms` 的 per-step 拆分提供时间盒。

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260219_ASSISTANT_LOOP_004_round2_cross_review.md`

