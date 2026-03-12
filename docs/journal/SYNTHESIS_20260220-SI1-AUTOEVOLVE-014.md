# SYNTHESIS: SI1 Self-Improvement Loop (自主迭代闭环)

- `thread_id`: `20260220-SI1-AUTOEVOLVE-014`
- `updated_at`: `2026-02-21`
- `status`: `resolved`

## 当前共识（Current Convergence）

- SI1 必须是受限闭环（governed pipeline），而不是“自动改代码并上线”。
- Promote 必须 HITL（Human-in-the-Loop）批准；未批准禁止写入/发布。
- 不新增 ExecuteRequest 顶层字段；扩展信息通过 `policy_context` 前向兼容透传。
- 任何阶段必须 evidence-by-default，且 replay-mode 下无新副作用。

## 分歧与决策点（Conflicts / Decision Points）

- SI1 在 MVP 阶段的“落点形态”：
  - A) 仅落 spec + 最小 CLI 骨架（Observe/Validate 可运行）
  - B) 直接落“可生成变更包”的 Promote（仍需 HITL）

## 裁决结论（Decision Outcome）

- Decision001: 选 A（Phase-1：Observe/Propose/Validate，不落 Promote 写入）
- Decision002: 选 A（HITL gate = admission MUST，用于 Phase-2 Promote）

## 建议的限界实验（Bounded Spike）

- Spike-SI1-A（建议）：先实现 Observe + Validate（无 Promote 写入），并用 1 个端到端用例验证：
  - 输出 signals/proposal/validation 三件套
  - 失败时 fail-closed 且 evidence 可回放
- Kill criteria：若出现任何 replay-mode 副作用、或绕过 HITL 的推广路径，立即终止 SI1 实现并回退到 spec-only。

## 下一步（Next）

- 已进入 Phase-1 实现（Observe/Propose/Validate）。Phase-2 Promote 单独立项与 bounded spike 后再进入裁决。
