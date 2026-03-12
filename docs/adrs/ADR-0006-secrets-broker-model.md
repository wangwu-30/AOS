# ADR-0006 密钥不下放：Secrets Broker/OAuth 代持模型（Secrets Broker Model）

- 状态（Status）：Accepted
- 日期（Date）：2026-02-13
- 相关规范（Related Specs）：`docs/specs/SECRETS_BROKER.md`、`docs/specs/POLICY_DELEGATION.md`

## 背景（Context）

第三方技能若能直接接触明文密钥（API key/refresh token），将导致不可控的数据外泄与责任风险。

## 决策（Decision）

- 默认“密钥不下放”：第三方技能不可直接读取明文 secrets。
- 通过 Secrets Broker（或 OAuth 代持）提供受控访问：
  - 短期 token（short-lived token）
  - 最小权限（least privilege）
  - 可撤销（revocable）
  - 全审计（audited）

## 备选方案（Alternatives）

1. 将密钥写入 skill 配置：
   - 简单但高风险，不可接受。
2. 将密钥下发给执行容器：
   - 仍会泄漏到第三方执行逻辑层面，风险过高。

## 取舍（Tradeoffs）

- Secrets Broker 增加平台复杂度，但这是 OS 级生态的硬门槛。

## 后果（Consequences）

- Tool API 必须支持“代表用户调用”（on-behalf-of）并记录 evidence。

## 风险与缓解（Risks & Mitigations）

- 风险：实现不当导致权限扩大或 token 滥用。
- 缓解：令牌绑定 workspace/skill/会话，设置 TTL 与强审计；关键动作强制 HITL。

## 可观测与验收（Metrics & Acceptance）

- 任意第三方技能执行过程中，不能读取明文 secrets。
- 所有“代表用户调用”的外部请求可审计、可撤销。

## 后续工作（Follow-ups）

- 在 `SECRETS_BROKER.md` 定义 token 颁发、绑定字段与撤销流程。

