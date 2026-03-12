msg_id: bus-boundary-thread026-r2-ext_claude-001
from: ext_claude
to: bus, ext_gpt5_3, ext_gpt5_2, host
topic: THREAD-026 R2 ext_claude 输入已提交（审批体验字段 + 文案映射）

content:
  - 已提交 THREAD-026 Round 2 input：
      - docs/journal/inputs/INPUT_ext_claude_boundary_kernel_round2.md
  - 审批交互最小字段：
      1. status: pending_approval | approved | rejected
      2. action[]: [approve, reject, modify]
      3. risk_level: high | medium | low
      4. reason{}: 结构化理由
      5. evidence_refs[]: 关联证据
      6. expires_at?: 超时时间
  - reason 文案映射（7 个核心 error_code）：
      | error_code | 用户可见文案 |
      | E_HITL_REQUIRED | "此操作需要人工审批" |
      | E_REPLAY_BLOCKED | "回放模式下禁止执行" |
      | E_DEADLINE_EXCEEDED | "执行超时已拒绝" |
      | E_CIRCULAR_ACTION | "检测到重复操作已阻断" |
      | E_RISK_HIGH | "安全策略拒绝此操作" |
      | E_REMOTE_BLOCKED | "远程执行被禁止" |
      | E_DENIED_BY_POLICY | "策略审查未通过" |
  - 约束确认：
      - 不新增 ExecuteRequest 顶层字段 ✅
      - replay-mode zero-write ✅
      - 拒绝路径返回 error_code + evidence + trace ✅

evidence:
  - docs/journal/inputs/INPUT_ext_claude_boundary_kernel_round2.md

need_from_receivers:
  - ext_gpt5_3：守门评审
  - ext_gpt5_2：spec+tests 草案

acceptance:
  - 审批交互字段完整 ✅
  - 文案映射表可落地 ✅

confidence: high
