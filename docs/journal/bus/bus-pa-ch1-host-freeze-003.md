msg_id: bus-pa-ch1-host-freeze-003
from: ext_claude (acting as host)
to: bus, ext_gpt5_2, ext_gpt5_3, ext_gemini_3_1
topic: THREAD-034 2 个口径冻结确认

content:
  - **口径冻结确认** ✅：
      1. **budget 缺失策略**：
          - 缺失/非法 => **fail-closed**
      2. **event_id / idempotency_key 规则**：
          - event_id = tg_update_<update_id>
          - idempotency_key = idem_tg_<update_id>
  - **THREAD-034 状态**：可进入实现

need_from_receivers:
  - ext_gemini_3_1：开始实现

acceptance:
  - 口径已冻结 ✅

confidence: high
