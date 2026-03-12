id: `20260225-ext_claude-dm2-round1-001`
author: `ext_claude`
topic: `DM2 Round 1 输入（产品/体验视角）`
position:
- 基于已锁定边界（single-writer / WAL / heartbeat / fallback），我作为产品/体验视角给出以下建议：
- 对 gpt5_2 问题的回应：
  1. daemon status 最小字段：当前建议够用，但建议加"下一次触发时间"（next_fire_at），便于用户感知"助手何时响应"；"队列长度"可暂时不加（P0 聚焦可靠性）。
  2. "连续2次失败阻断"阈值：从体验角度看**略偏严**，建议调整为"连续3次失败阻断"或"累计5次失败阻断"（给网络抖动/临时服务不可用留buffer），但保留"立即阻断"作为可选flag（--strict-mode）。
  3. 最小告警语义：P0 仅本地日志/stderr 即可，不需要额外告警渠道；后续可扩展为 webhook/email。
- 与 ext_gpt5_3 的差异：
  - 失败阈值：我建议连续3次（或累计5次）而非连续2次，给体验留buffer
  - status 字段：建议加 next_fire_at，不加队列长度
  - 告警：P0 仅本地日志，同意留后续
- 非协商约束保持：不新增 ExecuteRequest 顶层字段；扩展走 policy_context；replay-mode 无副作用。
evidence:
- THREAD-015 裁决（D/B/A）：`docs/journal/DECISIONS_20260224-OPENCLAW-GAP-015.md`
- THREAD-016 架构（C/B/A）：`docs/journal/DECISIONS_20260224-ASSISTANT-ARCH-016.md`
- MVP_012_SCHEDULER：`docs/specs/MVP_012_SCHEDULER.md`
- 回归基线：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`（当前77/77）
tradeoffs:
- 连续2次 vs 3次/累计5次：
  - 2次：更安全，但可能误伤临时网络抖动
  - 3次/累计5次：更宽容，提升体验但略增加风险
  - 建议：默认3次，可选--strict-mode 强制2次
- next_fire_at 字段：
  - 收益：用户可预期助手响应时间，提升信任
  - 成本：仅展示性字段，实现简单
- 告警语义：
  - P0 本地日志足够；后续扩展不影响核心
open_questions:
- 失败阈值是否需要区分"致命失败"（配置错误/权限问题）与"临时失败"（网络抖动/服务不可用）？
- 是否需要暴露"上次成功执行时间"作为健康状态指标？
proposal:
- Spike-DM2（P0 实现建议）：
  - CLI：run / run-once / status（加 --strict-mode 可选）
  - status 输出：state + last_fire_at + next_fire_at + consecutive_failures + cumulative_failures
  - 失败阈值：默认连续3次失败阻断，可选 --strict-mode 强制2次
  - WAL 最小事件：tick / fire_started / fire_finished / fire_failed（4类）
  - kill criteria：
    - 恢复一致性 < 99%（漏触发+重复触发 >1%）
    - replay-mode 出现新副作用
    - single-writer 失效（并发重复 fire）
acceptance:
- daemon status 可展示 state / last_fire_at / next_fire_at / consecutive_failures / cumulative_failures
- 失败阈值可配置（默认3次，可选--strict-mode=2次）
- P0 仅本地日志告警
- 回归门全绿
confidence: `high`
