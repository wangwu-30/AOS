# Synthesis

- `thread_id`: `20260214-EXT-COLLAB-001`
- `updated_at`: `2026-02-14`
- `sources`:
  - `docs/journal/inputs/INPUT_ext_gpt5_3_codex.md`
  - `docs/journal/inputs/INPUT_ext_gpt5_2.md`
  - `docs/journal/inputs/INPUT_ext_claude.md`
  - `docs/journal/inputs/INPUT_host_codex.md`

## Consensus

- 先落地协议，再扩展自动化，是当前阶段最小风险路径。
- 现有 MVP 安全基线（fail-closed / double gating / ASVP）应保持不降级。
- 协作流程必须从“聊天”提升为“文档化、可验证、可裁决”闭环。

## Conflicts

- `协作协议是否立即接入 admission tests`
  - 观点 A：立即接入，防止流程退化。
  - 观点 B：先文档化，下一迭代接入自动化以降低短期改动面。
- `PackageRunner 与 Executor 语义是否本轮统一`
  - 观点 A：立即统一可降低长期分叉成本。
  - 观点 B：MVP 阶段先维持路径稳定，后续通过映射渐进收敛。

## Issue Status

- `协议文档与线程落盘`: `resolved`
- `协议自动化准入`: `resolved`（evidence: `tests/test_admission_expert_collab_protocol.py`）
- `PackageRunner/Executor 语义收敛路径`: `resolved`（human override: Decision 005，拒绝过渡主路径）

## Recommended Direction

- 采用分阶段路线：
  - 阶段 1（当前）：协议与线程文档落盘，形成协作最低约束。
  - 阶段 2：协议契约校验纳入 admission tests（已落地最小准入测试）。
  - 阶段 3（后续）：启动 `Orchestrator -> Executor` bounded spike，验证可行后再决定是否进入主线实现。

## Decision Rationale

- 冲突 1（协议自动化准入）：
  - 继续采用最小 admission MUST 门禁，不将 Round 2 交叉评审输入提升为当前硬门禁。
  - 证据：`tests/test_admission_expert_collab_protocol.py`。
- 冲突 2（语义收敛落点）：
  - 最终裁决更新：Decision 005 已 supersede Decision 004，采用 Claude 方向，拒绝“过渡方案作为主路径”。
  - 当前执行策略：先做 `Orchestrator -> Executor` bounded spike，并验证 `PackageRunner` 可由 `LocalExecutor` 语义替换。
  - 硬回退阈值：若 spike 期间破坏现有 CLI 稳定 JSON 输出或 evidence/trace 落盘 schema，则立即回退为 `needs_decision`。
  - 证据：
    - `docs/journal/inputs/INPUT_ext_claude.md`（`id: 20260214-ext_claude-003`）
    - `docs/journal/DECISIONS_20260214-EXT-COLLAB-001.md`（Decision 005）
