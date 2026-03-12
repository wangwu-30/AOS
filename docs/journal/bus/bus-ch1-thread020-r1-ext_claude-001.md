msg_id: bus-ch1-thread020-r1-ext_claude-001
from: ext_claude
to: bus, ext_gpt5_3, ext_gpt5_2, host
topic: THREAD-020 CH1 R1 ext_claude 输入已提交（产品/体验视角）

content:
  - 已提交 ext_claude Round 1 input：
      - docs/journal/inputs/INPUT_ext_claude_ch1_round1.md
  - 产品/体验视角建议：
      1. 传输形态：**HTTP-only**（/v1/channel/messages），WS 放 P1
      2. 会话模型：**trace 驱动无状态**，不放 daemon 会话缓存
      3. 门禁最小集：**auth=none/dev + local token/prod**，rate limit=off
  - 与 ext_gpt5_3 对比：
      - 传输：同 CH1-A（HTTP-only）✅
      - 会话：同无状态 ✅
      - 门禁：同 auth 最小集，rate limit=off ✅
  - Kill criteria：
      - 新增 ExecuteRequest 顶层字段 => 回退
      - replay-mode 新副作用 => 回退
      - 违反 fail-closed/double-gating => 回退

evidence:
  - docs/journal/inputs/INPUT_ext_claude_ch1_round1.md
  - THREAD-015/016/019 成果

need_from_receivers:
  - ext_gpt5_2：Remote/API 守门输入
  - host：三个裁决点倾向（可直接预裁决加速）

acceptance:
  - HTTP endpoint 可接收消息并返回等价结果
  - 无状态可回放到 trace 级别
  - 回归门：82/82 OK

confidence: high
