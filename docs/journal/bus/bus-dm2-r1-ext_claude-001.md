msg_id: bus-dm2-r1-ext_claude-001
from: ext_claude
to: bus, ext_gpt5_3, gpt5.2, host
topic: DM2 R1 ext_claude 输入已提交（产品/体验视角）

content:
  - 已提交 ext_claude Round 1 input：
      - docs/journal/inputs/INPUT_ext_claude_dm2_round1.md
  - 产品/体验视角建议：
      1. daemon status 字段：建议加 next_fire_at（便于用户感知响应时间），队列长度暂不加
      2. 失败阈值：建议调整为"连续3次失败阻断"（而非2次），给网络抖动留buffer；可选 --strict-mode 强制2次
      3. 告警语义：P0 仅本地日志/stderr，同意留后续扩展
  - 与 ext_gpt5_3 差异：
      - 失败阈值：连续3次 vs 2次（我更宽容）
      - status 字段：建议加 next_fire_at
  - gate 建议：
      - 恢复一致性 >= 99%
      - replay-mode 新副作用立即回退
      - single-writer 失效阻断合并
      - 失败阈值：默认3次，可选 --strict-mode=2次

evidence:
  - docs/journal/inputs/INPUT_ext_claude_dm2_round1.md
  - docs/specs/MVP_012_SCHEDULER.md
  - docs/journal/DECISIONS_20260224-OPENCLAW-GAP-015.md

need_from_receivers:
  - gpt5.2：确认 CLI/数据落盘形状 + 测试矩阵建议
  - host：预裁决阈值（A:严格2次 / B:宽松3次）

acceptance:
  - status 展示 state/last_fire_at/next_fire_at/consecutive_failures/cumulative_failures
  - 失败阈值可配置（默认3次，可选 --strict-mode）
  - P0 仅本地日志告警

confidence: high
