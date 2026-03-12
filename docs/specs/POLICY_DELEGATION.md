# 策略与委托（Policy & Delegation）

## 目的（Purpose）

定义最小权限（Least Privilege）下的策略裁决与委托令牌（Delegation Token）语义，统一本地与云端执行入口的治理行为。

## 范围（Scope）

涵盖：
- PDP/PEP 分工
- policy 决策输出：canonical `allow/ask/deny`，兼容 wire `allow/deny/require_approval`
- delegation token 子集约束（capability/scope/budget/ttl）

## 核心概念（Concepts）

见 `docs/glossary.md`：PDP/PEP、委托（Delegation）、工作区（Workspace）。

## 接口/数据结构（Interfaces/Data）

### PolicyDecision

必须（MUST）包含：
- `decision`：`allow|deny|require_approval`
- `policy_disposition`：`allow|ask|deny`
- `reason_code`
- `error_code`：`decision != allow` 时必须为稳定错误码；`decision = allow` 时必须为 `null`
- `policy_id`（可选）
- `constraints`：例如 rate limits、budget slice

### Kernel Policy Engine（PDP）最小接口

策略决策点（PDP）必须（MUST）提供统一入口（可为函数或对象方法）：
- 输入：`ExecuteRequest` + `policy_context` + `skill_risk_level`（可选）
- 输出：`PolicyDecision`

默认值（Default）必须（MUST）满足：
- 循环检测阈值（cycle threshold）默认 `2`
- 当 `policy_context["policy_intent"]` 存在且为对象时，循环检测必须（MUST）启用，并在同一 `trace_id + turn_id` 作用域生效

边界条件（Boundary Conditions）必须（MUST）满足：
- 不得（MUST NOT）新增 `ExecuteRequest` 顶层字段；扩展仅允许通过 `policy_context`
- `policy_context` 未知键必须（MUST）前向兼容透传（forward-compatible passthrough）

### DelegationToken

必须（MUST）字段（草案）：
- `delegation_id`
- `workspace_id`
- `issuer_agent_id`
- `subject_agent_id`
- `capability_set`
- `scope`
- `budget_slice`
- `expires_at`
- `depth`

规则（MUST）：
- 子 token 只能收缩，不能扩张。

## 语义与状态机（Semantics/State Machine）

- 所有执行入口必须作为 PEP 强制策略。
- `ask`（wire alias: `require_approval`）必须进入 HITL gate，审批结果写 Evidence/Trace。
- 对启用循环检测的请求，同构动作（same action fingerprint）在同一 `trace_id + turn_id` 内达到阈值时，PEP 必须（MUST）返回 `deny`，并使用 `reason_code=cycle_detected`。
- 拒绝路径（`deny` 与 `ask`/`require_approval`）必须（MUST）记录 `kind=policy|error` evidence，并发出 `POLICY_DECIDED` 或 `ERROR` trace 事件。

## 错误与重试（Errors/Retry）

- `deny` 使用 `E_POLICY_DENY` 或 `E_CYCLE_DETECTED`（循环阻断）。
- `ask` / `require_approval` 使用 `E_HITL_REQUIRED`。

## 安全与隐私（Security/Privacy）

- delegation token 必须绑定 workspace 与 subject，避免跨租户滥用。

## 可观测性（Observability）

- 每次 policy decision 必须记录：输入摘要、输出 decision、reason_code。

## 兼容与版本（Compatibility/Versioning）

见 `VERSIONING_COMPAT.md`。

## 测试与验收（Tests/Acceptance）

- 子 token 扩权必须失败并可审计。
- HITL gate 必须可回放。
- 循环检测达到阈值时必须（MUST）返回 `E_CYCLE_DETECTED`，并且 evidence payload 至少包含：`decision/reason_code/error_code/fingerprint/count/threshold/trace_id/turn_id/skill_ref`。
