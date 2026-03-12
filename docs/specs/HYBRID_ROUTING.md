# 混合路由（Hybrid Routing）

## 目的（Purpose）

定义在本地/云端/混合能力扩展三种模式下的路由（Routing）规则与审计语义。

## 范围（Scope）

涵盖：
- 路由输入信号与输出
- 用户覆盖（User Override）
- PDP/PEP 分工与落点

## 核心概念（Concepts）

见 `docs/glossary.md`：混合执行（Hybrid Execution）、PDP/PEP、工作区（Workspace）。

## 接口/数据结构（Interfaces/Data）

路由输入（MUST）至少包含：
- `skill_requirements`：数据驻留（data residency）、egress、secrets、风险等级
- `user_preference`：默认偏好与临时 override
- `device_state`：离线/电量/网络状态等（可选）
- `cost_state`：预算、模型/执行成本（可选）

路由输出（MUST）包含：
- `target`：`local|remote`
- `rationale`：原因码列表（可枚举）
- `requires_human_approval`：是否需要审批

## 语义与状态机（Semantics/State Machine）

- 默认策略：自动路由 + 用户可覆盖（见 ADR-0002）。
- 高风险动作：即便用户覆盖，也必须通过审批门（HITL Gate）或强制远端执行。
- 路由决定必须写入 Evidence/Trace，并可回放。

## 错误与重试（Errors/Retry）

- 路由失败必须返回可解释错误码，例如 `E_ROUTING_NO_SAFE_TARGET`。

## 安全与隐私（Security/Privacy）

- 若目标为远端，传输数据必须最小化，并遵循端侧加密同步的默认隐私模型（见 ADR-0003）。

## 可观测性（Observability）

必须（MUST）记录路由：
- 输入信号摘要（脱敏）
- 输出 target
- rationale
- override 是否发生

## 兼容与版本（Compatibility/Versioning）

见 `VERSIONING_COMPAT.md`。

## 测试与验收（Tests/Acceptance）

- 用一组固定场景覆盖：离线、本地不支持能力、需要 secrets、高风险动作、用户覆盖。

