# 2026-02-19 外部专家协作线程 005 (External Expert Collaboration Thread 005)

- `thread_id`: `20260219-AL2-PLANNER-005`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-19`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

在 `Spike-AL1` 已落地（多步执行 + tool-calling + evidence/trace）基础上，引入可插拔 Planner（planner），支持：
- `deterministic`（确定性）planner：作为默认基线，保证可回归
- `llm` planner：以 LLM 生成结构化决策/plan，但必须严格遵守 fail-closed / replay-mode / 双闸门（double-gating）

## 范围 (In Scope)

- planner 接口（interface）与最小实现
- replay-mode 下 planner 行为（必须不触发远程）
- 远程 planner 的 gating/错误码稳定性
- evidence/trace 的落盘与可回放

## 非范围 (Out of Scope)

- streaming UI
- 并发多步/多 agent
- web browsing / 网络抓取

## 非协商约束 (Non-Negotiables)

- 不得破坏既有 CLI 稳定 JSON 输出与 evidence/trace schema（仅新增命令/字段，不回归现有契约）。
- replay-mode 下 MUST 禁远程（包括 planner 的远程 LLM）。
- 远程调用必须继续遵守双闸门：`remote_calls_armed=true` + `allow_network_egress=true`。

## 轮次进度 (Rounds)

- Round 0 (线程设定): 完成
- Round 1 (独立提案): 完成（实现落地）
- Round 2 (交叉评审): 完成（回归覆盖）
- Round 3 (综合): 完成（见 synthesis）
- Round 4 (裁决): 完成（见 decisions）

## Evidence (Links)

- `docs/journal/DECISIONS_20260219-ASSISTANT-LOOP-004.md`（AL1 gate/acceptance）
- `docs/specs/MVP_011_ASSISTANT_LOOP.md`（assistant loop 规范）
- `docs/journal/SYNTHESIS_20260219-AL2-PLANNER-005.md`
- `docs/journal/DECISIONS_20260219-AL2-PLANNER-005.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260219_AL2_PLANNER_005_round2_cross_review.md`

