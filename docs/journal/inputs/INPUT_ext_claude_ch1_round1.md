id: `20260225-ext_claude-ch1-round1-001`
author: `ext_claude`
topic: `THREAD-020 CH1 Round 1 输入（产品/体验视角）`
position:
- 三个待裁决点的产品/体验视角建议：
  1. 传输形态：**HTTP-only 最小入口**，WS 放 P1。理由：HTTP 更简单、调试更友好、curl 即可测试；WS 增加了状态管理复杂度，P0 聚焦最小可用。
  2. 会话模型：**trace 驱动无状态**，不放 daemon 会话缓存。理由：无状态更利于回放与审计，符合"可审计 AI 助理"定位；会话缓存增加复杂度与状态不一致风险。
  3. 门禁最小集：**auth=none（开发模式）/local token（生产）**，rate limit=off（P0 聚焦连通性，后续再扩展）。理由：P0 最小可用优先，auth 可通过 policy_context 扩展。
- 与 ext_gpt5_3 建议对比：
  - 传输形态：同 CH1-A（HTTP-only）✅
  - 会话模型：同 trace 驱动无状态 ✅
  - 门禁：同 auth 最小集，rate limit=off ✅
- 非协商约束保持：不新增 ExecuteRequest 顶层字段；replay-mode 无副作用；fail-closed 不降级。
evidence:
- THREAD-015/016/019 成果：UI-first、Hybrid、DM2 已交付
- MVP_012_SCHEDULER：`docs/specs/MVP_012_SCHEDULER.md`
- MVP_011_ASSISTANT_LOOP：`docs/specs/MVP_011_ASSISTANT_LOOP.md`
- 回归基线：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`（当前82/82）
tradeoffs:
- HTTP-only vs HTTP+WS：
  - HTTP：简单、可测试、调试友好，但无实时推送
  - WS：实时性好，但增加状态管理复杂度
  - 建议：P0 HTTP-only，P1 WS minimal
- 无状态 vs 会话缓存：
  - 无状态：利于回放、审计、更简单
  - 会话缓存：用户体验更连续，但增加复杂度
  - 建议：无状态优先
- auth/rate limit：
  - P0：auth=none 满足开发测试，rate limit=off 满足最小可用
  - 后续：可通过 policy_context 扩展 auth + rate limit
open_questions:
- 是否需要"实时推送"能力（P0 必须？还是 P1 特性）？
- 错误文案最小集：需要哪些错误码与用户可见文案？
proposal:
- Spike-CH1（P0）：
  - 传输：HTTP-only 最小入口（/v1/channel/messages）
  - 会话：trace 驱动无状态
  - 门禁：auth=none（dev）/local token（prod），rate limit=off
  - 输出契约：对齐现有 channel-stdio 稳定 JSON
  - Kill criteria：
    - 新增 ExecuteRequest 顶层字段
    - replay-mode 出现新副作用
    - 违反 fail-closed/double-gating
acceptance:
- HTTP endpoint 可接收消息并返回 assistant-loop 等价结果
- 无状态可回放到 trace 级别
- 回归门：82/82 OK
confidence: `high`
