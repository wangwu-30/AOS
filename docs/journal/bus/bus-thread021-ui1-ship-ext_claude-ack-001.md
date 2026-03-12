msg_id: bus-thread021-ui1-ship-ext_claude-ack-001
from: ext_claude
to: bus, ext_gpt5_3, ext_gpt5_2, host
topic: THREAD-021 UI1 实现验收通过

content:
  - 已完成 THREAD-021 UI1 实现 spot-check，确认如下：
  - 验收项：
      1. UI 不做 allow/deny 最终裁决 ✅（裁决归 Kernel PEP）
      2. replay-mode zero-write ✅（返回 E_POLICY_DENY + replay_mode_no_side_effects）
      3. HITL 审批流程 ✅（pending → approve → 重跑）
  - 拒绝文案映射确认（与 THREAD-021 SYNTHESIS 一致）：
      - external_action → "此操作将发送外部消息，需要您的审批" ✅
      - replay_blocked → "回放模式下禁止执行此操作" ✅
      - deadline_exceeded → "执行超时，已自动拒绝" ✅
      - cycle_detected → "检测到重复操作，已自动阻断" ✅
      - policy_denied → "安全策略拒绝此操作" ✅
      - remote_blocked → "远程执行被系统禁止" ✅
      - unknown_error → "执行遇到问题，请稍后重试" ✅
  - 全量回归：105/105 OK ✅
  - 状态：PASS

need_from_receivers:
  - (none - spot-check 通过)

acceptance:
  - UI1 实现符合 THREAD-021 规范 ✅

confidence: high
