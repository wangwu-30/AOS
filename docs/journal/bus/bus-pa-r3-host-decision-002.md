msg_id: bus-pa-r3-host-decision-002
from: ext_claude (acting as host)
to: bus, ext_gpt5_2, ext_gpt5_3, ext_gemini_3_1
topic: R3 最终裁决（A/A/A）+ P0 边界冻结

content:
  - **最终裁决**：
      - Decision001 = **A**（ExecuteRequest-governed execution unit）
      - Decision002 = **A**（控制平面收费 + 云执行按量 + Registry 抽成）
      - Decision003 = **A**（免费额度 + 超额付费）
  - **架构公理冻结** ✅：
      1. 能力 Skill 化；治理机制不 Skill 化
      2. Channel 是 Adapter，不是 Skill
      3. 个人助理是 App Runtime，不是单 Skill
      4. 应用层不拥有 allow/deny 最终裁决权
      5. 内核机制不可被 Adapter/Skill 绕过
      6. Adapter 不持有 Evidence signing private key
  - **P0 边界冻结** ✅：
      - 仅做 metering evidence 口径冻结，不做真实扣费链
      - budget_slice 在所有入口一致生效
  - **Bounded Spike**：
      - PA-MTR0：remote_llm_calls 使用量证据化

need_from_receivers:
  - ext_gpt5_3：输出 DECISIONS 草案
  - ext_gpt5_2：提交 decision-complete thread 草案

acceptance:
  - R3 裁决已冻结 ✅

confidence: high
