# OpenAI OAuth（Codex 模式）规范（OpenAI OAuth in Codex Mode）

## 目的（Purpose）

定义在 agentos-next 中通过“Codex OAuth 模式”进行 OpenAI 远程 LLM 调用的认证与治理约束：OAuth 授权码流程、token 代持（delegation）、绑定与撤销、安全闸门与证据语义，确保第三方技能无法接触明文凭据且避免意外远程调用。

## 范围（Scope）

涵盖：
- OAuth 2.0 授权码（Authorization Code）+ PKCE 的交互流程（用户连接账号）
- refresh/access token 的存储、刷新、撤销与审计（由受信组件代持）
- 调用时的 token 颁发（短期、最小权限、可撤销）
- 与 `SECRETS_BROKER.md`、`POLICY_DELEGATION.md`、`LLM_PROVIDER.md` 的集成点
- 安全闸门：默认禁止远程调用，显式武装后才允许

不涵盖：
- OpenAI 具体 API 端点字段的完整映射（由 provider 实现补齐）
- UI/浏览器实现细节

## 核心概念（Concepts）

见 `docs/glossary.md`：OAuth 授权码（Authorization Code）、PKCE、访问令牌（Access Token）、刷新令牌（Refresh Token）、OAuth 代持（OAuth Delegation）、密钥代理（Secrets Broker）、远程调用闸门（Remote Call Gate）。

## 接口/数据结构（Interfaces/Data）

### OAuthConnection（连接态）

工作区（workspace）级别必须（MUST）维护 OpenAI 连接态：
- `workspace_id`
- `provider_id=openai`
- `status`：`disconnected|pending|connected|error`
- `connected_at`（若 connected）
- `scopes`（已授权 scope 集合）
- `token_ref`：指向受信存储中的 refresh token 引用（不得暴露明文）

### OAuthStart（发起授权）

发起授权请求必须（MUST）由控制面/受信组件触发，并包含：
- `workspace_id`
- `trace`（TraceContext）
- `redirect_uri`（精确匹配）
- `state`（不可预测，绑定 workspace 与发起者）
- `pkce_verifier`/`pkce_challenge`
- `requested_scopes`

规则（MUST）：
- 发起 OAuth 必须（MUST）进入 HITL gate，并获得明确用户确认（consent）。
- 系统不得（MUST NOT）在后台自动触发 OAuth 登录或静默弹出浏览器。

### OAuthCallback（回调交换）

回调处理必须（MUST）验证：
- `state` 完整匹配（防 CSRF）
- `pkce_verifier` 与 challenge 匹配
- 授权结果（code / error）

回调交换成功后必须（MUST）：
- 将 refresh token 存入受信存储（Secrets Broker/OAuth 代持组件）
- 将 access token 视为短期缓存（可选），不得进入第三方执行环境
- 写 evidence（见下）

### TokenGrant（调用时短期令牌）

调用 OpenAI 时必须（MUST）通过 Secrets Broker 获取短期 token：
- token 必须（MUST）短期（short-lived）
- token 必须（MUST）绑定 `workspace_id`、`skill_ref`（或调用主体）与 scope
- token 必须（MUST）可撤销（按 workspace/skill/会话）

TokenGrant 字段见 `docs/specs/SECRETS_BROKER.md`。

## 语义与状态机（Semantics/State Machine）

### 连接流程（Connect）

1. 用户在受信控制面选择“连接 OpenAI（Codex OAuth 模式）”。
2. PDP 进行策略裁决；必须（MUST）为该动作产出 `policy` evidence。
3. 生成 `state` + PKCE，并打开授权页面（交互式）。
4. 回调后校验 `state`/PKCE，交换 token。
5. refresh token 代持存储，连接态变为 `connected`。
6. 记录 evidence：连接事件、scope、时间戳（不得记录明文 token）。

### 调用流程（Call）

调用必须（MUST）遵循 `docs/specs/LLM_PROVIDER.md` 的调用流水线，并额外要求：
- 即使已连接（connected），也必须（MUST）通过远程调用闸门（remote_calls_armed + allow_network_egress）。
- 必须（MUST）通过 Secrets Broker 颁发短期 token；不得直接使用 refresh token 进行 API 调用。

### 断开与撤销（Disconnect/Revocation）

用户断开连接时必须（MUST）：
- 撤销或失效化已代持的 refresh token（在可用的撤销机制下）
- 清理本地/受信存储中的 token 引用
- 记录 `policy`/`snapshot` evidence（实现可选，但必须可审计）

## 错误与重试（Errors/Retry）

必须（MUST）定义至少以下错误码：
- `E_OAUTH_REQUIRED`：未连接或授权缺失
- `E_OAUTH_STATE_MISMATCH`：state 校验失败
- `E_OAUTH_PKCE_MISMATCH`：PKCE 校验失败
- `E_OAUTH_DENIED`：用户拒绝授权或 provider 返回 denied
- `E_OAUTH_TOKEN_EXCHANGE_FAILED`
- `E_REMOTE_CALL_NOT_ARMED`：未武装远程调用（见 `LLM_PROVIDER.md`）

重试规则：
- 授权码交换失败不得（MUST NOT）盲目重试；必须提示用户重新连接或重新授权。

## 安全与隐私（Security/Privacy）

必须（MUST）：
- refresh token 只能存在于受信组件（本地控制面/受信云端），不得进入第三方技能执行环境（见 `docs/specs/SECRETS_BROKER.md`）。
- OAuth 回调必须校验 `state` 与 PKCE，防止 CSRF/代码注入。
- 任何 logs/evidence/trace 中不得记录授权码（code）、access token、refresh token。
- 远程调用缺省关闭：无论是否 connected，未武装（armed）都必须拒绝真实网络调用（fail closed）。

说明（MAY, MVP 实现选择）：
- 在早期迭代中，“受信组件”可以是本地控制面的 token 存储（例如仅控制面可读的凭证文件），用于降低接入成本；但第三方技能执行环境仍不得读取该存储。

应该（SHOULD）：
- 最小 scope：只申请完成 LLM 调用所需的最小权限。
- 将 OpenAI egress 域名加入 `net_allowlist` 的流程纳入策略治理（见 `docs/specs/SANDBOXING.md`）。

## 可观测性（Observability）

必须（MUST）记录：
- connect/disconnect 的策略裁决 evidence（`kind=policy`）
- 调用的 `llm_io` evidence（见 `docs/specs/LLM_PROVIDER.md`）
- 关键状态变更的 trace 事件（例如 POLICY_DECIDED、ROUTED、ERROR）

## 兼容与版本（Compatibility/Versioning）

- 连接态、授权事件与调用 evidence 必须（MUST）带 `schema_version`。
- 迁移策略见 `docs/specs/VERSIONING_COMPAT.md`。

## 测试与验收（Tests/Acceptance）

必须（MUST）覆盖：
- state/PKCE 不匹配时拒绝并可审计（不产生 connected 状态）。
- 断开连接后，短期 token 颁发被拒绝（在可接受传播延迟内）。
- 未武装远程调用时，即使已 connected 也不得发起真实网络请求。
