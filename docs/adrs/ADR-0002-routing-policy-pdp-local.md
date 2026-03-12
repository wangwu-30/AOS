# ADR-0002 路由策略：自动路由 + 用户覆盖（Policy Routing, PDP Local）

- 状态（Status）：Accepted
- 日期（Date）：2026-02-13
- 相关规范（Related Specs）：`docs/specs/HYBRID_ROUTING.md`、`docs/specs/POLICY_DELEGATION.md`

## 背景（Context）

混合执行要求系统自动在本地/云端间做路由（Routing），但消费级助理也要求用户在关键场景能覆盖默认选择。

## 决策（Decision）

- 默认由策略引擎自动路由（risk/data/cost），用户可覆盖（force local/force remote）。
- 策略决策点（PDP）默认在本地控制面，策略执行点（PEP）在每个执行入口（本地与云端）强制执行。

## 备选方案（Alternatives）

1. 每次都让用户选：
   - 透明，但交互成本高，破坏助理体验。
2. 完全由 skill 合同强制：
   - 简单，但生态约束过强，难满足临时偏好。
3. 云端 PDP：
   - 便于统一治理，但隐私与离线更难。

## 取舍（Tradeoffs）

- 本地 PDP 要处理策略分发与缓存，但换来更强的隐私控制与离线能力。

## 后果（Consequences）

- 需要明确 override 的记录方式（写入 Evidence/Trace）与审计语义。

## 风险与缓解（Risks & Mitigations）

- 风险：用户 override 导致安全边界被绕开。
- 缓解：override 也必须经过策略边界（例如只能在低风险工具上覆盖），高风险仍强制审批。

## 可观测与验收（Metrics & Acceptance）

- 每次路由决定必须可解释、可审计（记录原因与输入信号）。
- override 的使用率、失败率、事故率可统计。

## 后续工作（Follow-ups）

- 完成 `docs/specs/HYBRID_ROUTING.md` 的决策记录字段。

