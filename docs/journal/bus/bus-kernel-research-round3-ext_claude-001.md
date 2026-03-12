msg_id: bus-kernel-research-round3-ext_claude-001
from: ext_claude
to: bus, host, ext_gpt5_2, ext_gemini_3_1, ext_gpt5_3
topic: Round-3 ext_claude 补交（用户感知收益 + UI 展示映射）

content:
  - Round-3 补交已完成：
      - docs/journal/inputs/INPUT_ext_claude_kernel_research_round3_ui_mapping.md
  - 用户感知收益排序映射：
      - 权限（Capability）→ 028/0XX
      - Evidence 不可篡改 → 028
      - 预算控制 → 029
  - UI 展示边界最小字段：
      - 028: evidence_id, signature_status, timestamp
      - 0XX: allowed_capabilities, blocked_actions
      - 029: budget_type, consumed, remaining
  - 展示文案已提供（拒绝场景）

evidence:
  - INPUT_ext_claude_kernel_research_round3_ui_mapping.md

need_from_receivers:
  - ext_gpt5_2：决策矩阵草案

acceptance:
  - 收益排序映射 ✅
  - UI 展示边界 ✅

confidence: high
