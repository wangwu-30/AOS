# 密钥代理与代持（Secrets Broker / OAuth Delegation）

## 目的（Purpose）

定义“密钥不下放”的系统约束：第三方技能不可直接读取明文 secrets，通过受控 broker 获取短期最小权限 token。

## 范围（Scope）

涵盖：
- secrets 类型（api key、oauth refresh/access token 等）
- token 颁发、绑定、撤销与审计

## 核心概念（Concepts）

见 `docs/glossary.md`：Secrets Broker、最小权限（Least Privilege）。

## 接口/数据结构（Interfaces/Data）

### TokenGrant（授权结果）

必须（MUST）包含：
- `token`（短期）
- `expires_at`
- `bound_workspace_id`
- `bound_skill_ref`
- `scopes`

### Revocation（撤销）

必须（MUST）支持：
- 按 workspace、skill、会话维度撤销

## 语义与状态机（Semantics/State Machine）

- 所有“代表用户调用”（on-behalf-of）必须写 Evidence，并可回放。

## 错误与重试（Errors/Retry）

- broker 拒绝必须返回 `E_POLICY_DENY` 或更细分错误。

## 安全与隐私（Security/Privacy）

- 明文 secrets 只能存在于受信组件（本地控制面/受信云端），不得出现在第三方执行环境。

## 可观测性（Observability）

- 授权/撤销事件必须可审计。

## 兼容与版本（Compatibility/Versioning）

见 `VERSIONING_COMPAT.md`。

## 测试与验收（Tests/Acceptance）

- 第三方执行中无法读取明文 secrets；撤销后 token 立即失效（在可接受的传播延迟内）。

