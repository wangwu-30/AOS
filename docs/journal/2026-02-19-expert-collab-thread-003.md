# 2026-02-19 外部专家协作线程 003 (External Expert Collaboration Thread 003)

- `thread_id`: `20260219-OPENCLAW-ASSISTANT-003`
- `status`: `round_2_in_progress`
- `updated_at`: `2026-02-19`
- `owner`: `ext_gemini_flash`

> Legacy record: `docs/journal/2026-02-19-openclaw-assistant-003.md` (non-standard filename). This file is the protocol-conforming thread entrypoint.

## 问题陈述 (Problem Statement)

基于 OpenCLAW 风格定义 AgentOS Next 的助手级能力，评估必要功能（记忆、主动任务、定时任务、编程、子 Agent 等）在 AgentOS Skills 中的映射、优先级以及 Remote API 的扩展需求。

## 范围 (In Scope)

- 必要功能到 AgentOS Skills 的映射。
- 功能优先级定义 (P0/P1)。
- Remote API 对调度 (Scheduler) 与通道 (Channel) 的扩展支持。
- Skill 包形态与 Manifest 建议。
- OpenViking L0/L1/L2 分层记忆可迁移点与 Remote API 的承载方式。

## 轮次进度 (Rounds)

- Round 0 (线程设定): 完成
- Round 1 (独立提案): 进行中
- Round 2 (交叉评审): 进行中
- Round 3 (综合): 待开始
- Round 4 (裁决): 待开始

## 消息记录 (Message Log)

- bus-021 (ext_gpt5_3): OpenCLAW 风格助手映射/优先级/补项（架构视角）
- bus-027 (gpt5.2): 必要功能逐项映射（skill 设计视角）+ 优先级调整建议
- bus-029 (ext_claude): OpenViking L0/L1/L2 分层记忆借鉴
- bus-030 (gpt5.2): OpenViking 映射到 AgentOS（skill 设计视角）+ MVP-010 记忆架构建议
- ext_gemini_flash update: Remote API 扩展提案（Scheduler/Channel/Budget 等）
- gpt5.2 input: `docs/journal/inputs/INPUT_ext_gpt5_2.md` block `20260219-ext_gpt5_2-013`（Manifest 最小集 + memory_context bounded spike）

## 待办事项 (To-Do)

- [x] gpt5.2: 补充 Skill 包形态与最小 manifest 字段建议（已在 `20260219-ext_gpt5_2-013` 提交）
- [ ] ext_gemini_flash: Round 3 综合（Synthesis）
- [ ] host: Round 4 裁决（Decision）

