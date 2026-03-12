# DECISIONS: OpenClaw Gap → AgentOS Next Roadmap

- `thread_id`: `20260224-OPENCLAW-GAP-015`
- `updated_at`: `2026-02-24`
- `status`: `accepted`

## Decision 001: P0 路线（先补齐哪类能力）

- **状态**: `accepted`
- **结论**: 选 **D) UI-first + Channels-embedded**
  - P0 以 **可审计交互（auditable interaction）** 为主：先打通 UI + HITL（Human-in-the-Loop）审批流 + trace/evidence 可视化闭环。
  - Channels 作为输入源嵌入 UI 闭环：先做 local gateway channel（HTTP/WS/stdio），P1 再扩展 Telegram/Discord。
  - Browser/Computer Use（浏览器/桌面自动化）作为 P1 bounded spike（更高风险能力，先不放进 P0）。

## Decision 002: 长期运行语义（daemon）是否进入 P0

- **状态**: `accepted`
- **结论**: 选 **B) daemon 进 P0（保留显式 runner/tick fallback）**
  - daemon 必须配套更严格 admission gates：single-writer、WAL 恢复、健康检查/心跳、幂等触发/去重。
  - 同时保留显式 runner/tick 作为 deterministic fallback（可回放入口与故障兜底）。

## Decision 003: 长期记忆（vector retrieval）是否进入 P0

- **状态**: `accepted`
- **结论**: 选 **A) file-backed + naive search + compact 进 P0；vector retrieval 进 P1**
  - P0 聚焦“治理与可回放（governance + replayability）”：TTL/tombstone/compact、检索链（retrieval chain）落 trace/evidence、最小质量基线。
  - P1 若引入向量检索（vector retrieval/embeddings），必须先补齐 PII redaction + budget gates，并以 bounded spike 验证。

## P0 Bounded Spikes（建议组合）

- Spike-UI1：最小 UI（建议先 TUI）+ HITL 审批流 + 可视化 trace/evidence 闭环
- Spike-CH1：local gateway channel（HTTP/WS）+ 去重/幂等 + trace/evidence 贯通（P1 再做 Telegram/Discord）
- Spike-DM2：daemon（single-node）+ single-writer + WAL 恢复 + health/heartbeat + runner/tick fallback
- Spike-MEM-P0-ext：memory 治理增强（非向量）+ 检索链 evidence + 简单质量基线指标

## 单一硬回退阈值（One Hard Rollback Trigger）

- 任一 spike 若导致 replay-mode 下出现新副作用（any write / any remote call），立即回退并阻断合并（fail-closed）。

## Gate（进入 accepted 前必须通过的门禁）

1. 不新增 ExecuteRequest 顶层字段（扩展优先 policy_context）。
2. fail-closed / replay-mode / evidence-by-default 不降级。
3. 所选路径必须配套 bounded spike + kill criteria（不能直接拍板）。

## Acceptance（可验证验收）

- 本线程三件套存在：
  - `docs/journal/2026-02-24-expert-collab-thread-015.md`
  - `docs/journal/SYNTHESIS_20260224-OPENCLAW-GAP-015.md`
  - `docs/journal/DECISIONS_20260224-OPENCLAW-GAP-015.md`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

