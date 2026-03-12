# 2026-02-19 外部专家协作线程 006 (External Expert Collaboration Thread 006)

- `thread_id`: `20260219-AL3-STDIO-006`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-19`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

将 assistant loop 接入“会话型输入通道”（stdio session）：stdin 多行输入触发多轮 assistant loop，保证：
- trace correlation（同 session 复用 `trace_id`）
- evidence/trace 落盘稳定
- 不破坏现有 `mvp channel-stdio` 输出契约（推荐新命令）

## 范围 (In Scope)

- 新增 `mvp assistant-loop-stdio`（或等价新命令）
- session correlation 与 turn/span 派生规则
- 输出稳定 JSON line（per message）

## 非范围 (Out of Scope)

- Telegram/Discord 等第三方 channel
- streaming UI

## 非协商约束 (Non-Negotiables)

- 不得破坏 `mvp channel-stdio` 既有输出契约（新增命令优先）。
- replay-mode 下 MUST 禁远程；双闸门不降级。

## 轮次进度 (Rounds)

- Round 0 (线程设定): 完成
- Round 1 (独立提案): 完成（实现落地）
- Round 2 (交叉评审): 完成（回归覆盖）
- Round 3 (综合): 完成（见 synthesis）
- Round 4 (裁决): 完成（见 decisions）

## Evidence (Links)

- `docs/journal/DECISIONS_20260219-ASSISTANT-LOOP-004.md`（AL1 gate/acceptance）
- `docs/journal/SYNTHESIS_20260219-AL3-STDIO-006.md`
- `docs/journal/DECISIONS_20260219-AL3-STDIO-006.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260219_AL3_STDIO_006_round2_cross_review.md`

