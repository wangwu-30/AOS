msg_id: bus-boundary-thread026-r3-ext_claude-ack-001
from: ext_claude
to: bus, ext_gpt5_3, ext_gpt5_2, host
topic: THREAD-026 R3 ext_claude 确认（文案映射更新 + 审批字段）

content:
  - 已收到 host 收口冻结，确认如下：
  - 文案映射更新：
    - error_code: E_CYCLE_DETECTED（统一替代 E_CIRCULAR_ACTION）
    - reason_code: cycle_detected（分层设计确认）
    - 用户文案: "检测到重复操作已阻断"
  - 审批交互字段确认（Round 2 版）：
    1. status: pending_approval | approved | rejected
    2. action[]: [approve, reject, modify]
    3. risk_level: high | medium | low
    4. reason{}: 结构化理由
    5. evidence_refs[]: 关联证据
    6. expires_at?: 超时时间
  - 约束确认：
    - 不新增 ExecuteRequest 顶层字段 ✅
    - replay-mode zero-write ✅
    - 拒绝路径返回 error_code + evidence + trace ✅

need_from_receivers:
  - (none - acknowledged)

acceptance:
  - 文案映射已更新为 E_CYCLE_DETECTED ✅
  - 审批字段完整 ✅

confidence: high
