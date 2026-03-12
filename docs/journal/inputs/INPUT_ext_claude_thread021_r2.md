id: `20260226-ext_claude-thread021-r2-001`
author: `ext_claude`
topic: `THREAD-021 Round 2：验收壳最小字段与拒绝文案映射（UX 层）`
position:
- 基于 Kernel-first 共识，明确 UI 仅作为"验收壳"而非"决策者"：
- 禁止放到 UI 的逻辑：
  - allow/deny 最终裁决（Kernel PEP 独有一只）
  - policy 策略配置（由 policy_context 传入）
  - 风险级别判定（由 Kernel 返回）
- UI 仅负责：
  1. 展示审批请求（status + action + reason + evidence_refs）
  2. 收集用户决策（approve/reject/modify）
  3. 展示执行结果 + trace/evidence 可视化
- 审批展示字段（Kernel 返回 → Demo 展示）：
  - status: pending_approval | approved | rejected
  - action: [approve, reject, modify]
  - reason_code: string（如 "external_action"）
  - reason_message: 开发者可见详细原因
  - user_facing_message: 用户可见简化文案
  - evidence_refs: [string]
  - expires_at?: ISO timestamp
- 拒绝文案映射（Kernel 返回 reason_code → Demo 展示 user_facing_message）：
  | reason_code | user_facing_message |
  |------------|-------------------|
  | external_action | "此操作将发送外部消息，需要您的审批" |
  | replay_blocked | "回放模式下禁止执行" |
  | deadline_exceeded | "执行超时已自动拒绝" |
  | cycle_detected | "检测到重复操作已阻断" |
  | policy_denied | "安全策略拒绝此操作" |
  | remote_blocked | "远程执行被禁止" |
  | unknown_error | "执行遇到问题，请稍后重试" |
evidence:
- THREAD-026 Phase-1 accepted（Kernel Policy Engine）
- docs/specs/EVIDENCE_TRACE.md
tradeoffs:
- UI 简洁 vs 功能完整：
  - 简洁：只展示必要信息
  - 完整：展示完整 trace/evidence 链路
  - 建议：P0 简洁展示，详情可折叠
open_questions:
- 是否需要展示 confidence_score（模型置信度）？
- 是否需要支持"不再询问"选项？
proposal:
- Spike-UI1-v2（P0）：
  - 展示层：status + action + reason_code + user_facing_message + evidence_refs
  - 交互：approve / reject / modify 按钮
  - 禁止：UI 不做 allow/deny 裁决
  - Kill criteria：
    - UI 绕过 Kernel PEP 直接返回 allow/deny → 回退
    - 审批状态无法追溯到 evidence_refs → 回退
acceptance:
- 审批展示字段完整（7 字段）✅
- 拒绝文案映射表（7 条）✅
- UI 不包含裁决逻辑 ✅
confidence: `high`
