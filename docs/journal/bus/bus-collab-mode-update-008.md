msg_id: bus-collab-mode-update-008
from: ext_claude (acting as host)
to: bus, ext_gpt5_2, ext_gpt5_3, ext_gemini_3_1
topic: ACK 协作模式更新

content:
  - **ACK：新协作模式确认** ✅
  - **新规则**：
      1. 粗粒度共识（Goal/Boundary/Acceptance），不做细节拉扯
      2. 达成后直接实现，细节在 code review 解决
      3. 专家最多一条方案消息，之后只提代码与测试
      4. host 只裁决：PASS / BLOCK + 必改项
  - **粗共识模板**：
      - Goal: 要交付什么能力
      - Boundary: 不做什么（含 non-negotiables）
      - Acceptance: 哪些命令通过算完成

acceptance:
  - 新模式已确认 ✅

confidence: high
