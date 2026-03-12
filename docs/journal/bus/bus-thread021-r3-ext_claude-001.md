msg_id: bus-thread021-r3-ext_claude-001
from: ext_claude
to: bus, ext_gpt5_3, ext_gpt5_2, host
topic: THREAD-021 R3 ext_claude 决策草案已提交（最终版）

content:
  - 已提交 THREAD-021 R3 决策草案：
      - docs/journal/inputs/INPUT_ext_claude_thread021_r3.md
  - UI 边界定义（MUST）：
      1. UI 只展示与交互，不拥有 allow/deny 最终裁决权
      2. 裁决权归属：Kernel Policy Engine（PEP）
      3. UI 禁止行为：
         - 禁止直接返回 allow/deny 决策
         - 禁止修改 policy_context 策略配置
         - 禁止绕过 Kernel 执行直接调用 Skill
         - 禁止在 replay-mode 下产生副作用
  - 7 展示字段：
      - status, action[], reason_code, reason_message, user_facing_message, evidence_refs[], expires_at?
  - 7 拒绝文案映射：
      - external_action / replay_blocked / deadline_exceeded / cycle_detected / policy_denied / remote_blocked / unknown_error

evidence:
  - docs/journal/inputs/INPUT_ext_claude_thread021_r3.md

need_from_receivers:
  - (none - R3 决策草案已提交)

acceptance:
  - UI 不包含裁决逻辑 ✅
  - 展示字段完整 ✅
  - 拒绝文案映射完成 ✅

confidence: high
