# 2026-02-14 外部专家协作线程 001（External Expert Collaboration Thread 001）

- `thread_id`: `20260214-EXT-COLLAB-001`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-14`
- `owner`: `human + codex`

## 问题陈述（Problem Statement）

在 `agentos-next` 当前 MVP 骨架下，引入并固化“外部专家协作协议（Expert Collaboration Protocol）”，并输出第一轮深度分析建议，确保后续多专家协作具备统一接口、可追踪证据与可裁决流程。

## 范围（In Scope）

- 新增专家协作规范与线程文件结构。
- 输出第一位外部专家（`ext_gpt5_3_codex`）的结构化建议。
- 形成可进入后续交叉评审与裁决的综合基线。

## 非范围（Out of Scope）

- 本线程不直接修改运行时代码行为。
- 本线程不引入新网络能力或外部依赖。

## 非协商约束（Non-Negotiables）

- 默认 fail-closed 不得被削弱。
- 协作文档不得包含敏感信息（token/key/私钥等）。
- 建议必须可验证，且可映射到测试/命令证据。

## 当前事实（Current Facts）

- `PYTHONPATH=src python3 -m unittest discover -s tests -v`：`25/25` 通过。
- 当前骨架已具备：
  - ASVP 签名验证链路
  - 远程调用双闸门（double gating）
  - trace/evidence 落盘
  - `mvp release-pack` 证据打包入口

## 轮次进度（Rounds）

- Round 0（线程设定）：完成
- Round 1（独立提案）：完成（见 `docs/journal/inputs/INPUT_ext_gpt5_3_codex.md`）
- Round 2（交叉评审）：完成（见 `docs/journal/inputs/INPUT_host_codex.md` 与 `docs/journal/inputs/INPUT_ext_gpt5_2.md`）
- Round 3（综合）：完成（见 `docs/journal/SYNTHESIS_20260214-EXT-COLLAB-001.md`）
- Round 4（裁决）：完成（见 `docs/journal/DECISIONS_20260214-EXT-COLLAB-001.md`）

## 最终裁决摘要（Final Decision Summary）

- 冲突 1（协议自动化准入）：`accepted`
  - 采用最小 admission MUST 门禁；Round 2 交叉评审输入暂不升为当前硬门禁。
- 冲突 2（语义收敛落点）：`accepted`
  - 决策更新（Decision 005 supersedes Decision 004）：拒绝“过渡方案作为主路径”，改为先验证 `Orchestrator -> Executor` 直连路径。
  - bounded spike 目标：验证 `PackageRunner` 可由 `LocalExecutor` 语义替换。
  - 硬回退阈值：若 spike 期间破坏现有 CLI 稳定 JSON 输出或 evidence/trace 落盘 schema，则立即回退并重开 `needs_decision`。
- 身份记录策略：保持并存
  - `INPUT_ext_gpt5_2.md` 作为外部专家输入。
  - `INPUT_host_codex.md` 作为主持方交叉评审补充输入。
  - `INPUT_ext_claude.md` 作为外部专家输入（最终由 human override 采用其 `-003` 方向）。

## 输出要求（Expected Outputs）

- 每位专家按 Message Contract 提交输入文件。
- 综合文件按 `resolved|needs_decision|blocked_by_missing_evidence` 标注。
- 冲突项必须先执行限界实验（Bounded Spike）再进入决策。

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260214_EXT_COLLAB_001_round2_cross_review.md`

