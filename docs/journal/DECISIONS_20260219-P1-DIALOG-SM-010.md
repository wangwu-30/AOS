# DECISIONS: P1 Multi-Turn Dialog State Machine Spike

- `thread_id`: `20260219-P1-DIALOG-SM-010`
- `updated_at`: `2026-02-19`
- `status`: `accepted`

## Decision 001: 以事件为中心的最小状态机（Event-Centric Minimal State Machine）

- 状态：`accepted`
- 结论：
  - 对话状态机以“事件（events）驱动 + replay 重建”为第一原则。
  - 状态集合最小化为：`OPEN|RUNNING|BLOCKED|IDLE|CLOSED|FAILED`。
- 原因：
  - 更符合 AgentOS Next 的“证据默认（evidence by default）/可回放（replayable）”主张。
  - 避免把关键语义埋在内存对象与隐式分支里，难以审计与回归。

## Decision 002: 持久化复用 trace/evidence（Reuse Trace/Evidence as Persistence）

- 状态：`accepted`
- 结论：
  - 事件日志落在 `data/traces/<trace_id>.jsonl`（追加式 JSONL）。
  - 事件相关 payload 的大对象（例如 state snapshot/turn result）落在 `data/evidence/...`，由 trace event 通过 `evidence_refs` 引用。
- Kill criteria（终止条件）：
  - 若必须引入新的对外持久化契约或迁移现有 trace/evidence 布局，且无法在 P1 范围内保持兼容，则停止该 spike 并回退为“仅文档定义”。

## Gate（必须通过的门禁）

1. 不得破坏既有 CLI 契约（CLI contract）与既有测试集。
2. replay-mode（`replay_mode=true`）语义不降级：禁止远程依赖调用，允许只读重放并可确定性重建状态。
3. 最小状态集合与事件集合必须可被自动化测试覆盖（至少覆盖 3 条核心路径：成功、失败、缺证据阻塞）。

## Acceptance（可验证验收）

- 基线（当前可执行，不允许回归）：
  - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_admission_expert_collab_protocol.py' -v`
  - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
- Spike 专用（待实现）：
  - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_p1_dialog_state_machine_replay.py' -v`

## Evidence（证据）

- `docs/journal/2026-02-19-expert-collab-thread-010.md`
- `docs/journal/SYNTHESIS_20260219-P1-DIALOG-SM-010.md`
- `docs/journal/DECISIONS_20260219-P1-DIALOG-SM-010.md`
- `docs/specs/EXPERT_COLLAB_PROTOCOL.md`
- `docs/specs/EVIDENCE_TRACE.md`
- `docs/specs/MVP_014_DIALOG_STATE_MACHINE.md`
- `src/agentos_next/kernel/dialog_state_machine.py`
- `src/agentos_next/cli.py`
- `tests/test_spike_p1_dialog_state_machine_replay.py`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

