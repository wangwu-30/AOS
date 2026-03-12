# LLM 提供方与调用（LLM Provider & Calling）

## 目的（Purpose）

定义 agentos-next 中“LLM 调用”的统一抽象：Provider 接口、请求/响应数据结构、证据（Evidence）语义与安全闸门（Safety Gating），以避免意外远程调用并支撑可审计、可回放与可治理的推理调用。

## 范围（Scope）

涵盖：
- LLM Provider 抽象与注册（registry）
- 模型选择、调用参数与返回规范化
- 认证模式（API Key / OAuth Delegation / 无认证本地模型）
- 安全闸门：默认禁止远程调用（remote call），显式武装（arming）后才允许
- Evidence/Trace 记录要求（`kind=llm_io`）

不涵盖：
- 具体 SDK 实现细节与 UI
- 提示词工程（prompt engineering）最佳实践

## 核心概念（Concepts）

见 `docs/glossary.md`：LLM 提供方（LLM Provider）、远程调用闸门（Remote Call Gate）、网络出口（Egress）、密钥代理与代持（Secrets Broker / OAuth Delegation）、证据（Evidence）。

## 接口/数据结构（Interfaces/Data）

### ProviderId / ModelId

- `provider_id`：字符串标识（例如 `openai`、`local_mock`、`minimax`）。
- `model_id`：Provider 内部的模型标识（例如 `gpt-4.1`）。

规则：
- `provider_id` 与 `model_id` 必须（MUST）写入 `llm_io` evidence。

### LLMCallRequest

LLM 调用请求必须（MUST）包含：
- `schema_version`
- `workspace_id`
- `trace`：TraceContext（见 `docs/specs/EVIDENCE_TRACE.md`）
- `provider_id`
- `model_id`
- `messages`：标准化消息数组（system/user/assistant/tool）
- `idempotency_key`：用于去重与回放（见 `docs/specs/EVIDENCE_TRACE.md` 与 `docs/specs/EXECUTOR_API.md` 的习惯用法）
- `safety`：安全闸门输入（见下）

LLM 调用请求应该（SHOULD）包含：
- `tool_schema`/`tools` 与 `tool_choice`（若支持 tool calling）
- `response_format`（若支持结构化输出）
- `generation_params`：如 `temperature`、`top_p`、`max_output_tokens`、`seed`
- `timeout_ms`
- `user_visible_reason`：用于 HITL/审计的解释字符串（脱敏）

LLM 调用请求可以（MAY）包含：
- `input_artifact_refs`：将 Evidence/Artifact 作为输入引用，而非内联大文本
- `redaction_profile`：脱敏策略选择（实现可选）

### LLMCallSafetyGate

为避免意外远程调用，必须（MUST）引入显式安全闸门信号：
- `remote_calls_armed`：布尔值；默认为 `false`
- `allow_network_egress`：布尔值；默认为 `false`
- `requires_human_approval`：布尔值；由 PDP 决策输出（见 `docs/specs/POLICY_DELEGATION.md`）
- `approved_by_human`：布尔值；仅在 HITL 通过后为 `true`

规则（MUST）：
- 当目标 Provider 需要网络（remote LLM）时，`remote_calls_armed=true` 且 `allow_network_egress=true` 才允许发起真实网络请求。
- 若 PDP 输出 `requires_human_approval=true`，则必须（MUST）在 `approved_by_human=true` 前拒绝调用并返回 `E_HITL_REQUIRED`。
- 缺省配置下必须（MUST）拒绝任何远程 LLM 调用（fail closed）。
- 调用方若已经确定某个 phase 将使用 remote provider，必须（MUST）在进入该 phase 主执行前完成双闸门预检；若闸门不满足，必须（MUST）直接返回稳定错误码，不得（MUST NOT）先消耗 provider token、网络预算或写出伪造 step 成功记录。

### LLMCallResponse

LLM 调用响应必须（MUST）包含：
- `schema_version`
- `provider_id`、`model_id`
- `output`：标准化输出（例如 `assistant_message` + `tool_calls`）
- `usage`：token/计费用量（若 provider 可提供）
- `finish_reason`
- `provider_request_id`/`provider_response_id`（若可得）
- `evidence_ref`：指向 `kind=llm_io` 的 EvidenceRef（见 `docs/specs/EVIDENCE_TRACE.md`）

### LLM Provider Interface（逻辑接口）

Provider 实现必须（MUST）提供：
- `supports(model_id)`：模型可用性判断
- `call(request) -> response`
- `redact_for_evidence(request/response)`：用于 evidence 的脱敏视图（实现可内置）

Provider 实现必须（MUST）声明能力与约束（供路由/策略使用）：
- 是否需要网络
- 是否需要 secrets broker（API key 或 OAuth token）
- 可用模型列表（或匹配规则）
- 默认/最大输出 token、上下文长度（若可得）

### MiniMax 提供方（MiniMax Provider）

当 `provider_id = "minimax"` 时，运行时必须（MUST）满足：
- 默认 `base_url = "https://api.minimax.io/v1"`。
- 若用户位于中国大陆环境，可以（MAY）通过 `MINIMAX_BASE_URL` 覆盖为 `https://api.minimaxi.com/v1`。
- 认证必须（MUST）通过 `MINIMAX_API_KEY` 提供。
- `model_id` 应该（SHOULD）优先取显式传入值，其次取 `MINIMAX_MODEL_ID`，否则可以（MAY）回退到实现内默认模型。
- 请求必须（MUST）走 OpenAI-Compatible `POST /chat/completions` 接口，并保持双闸门（double gate）与 replay-mode 约束不降级。

## 语义与状态机（Semantics/State Machine）

### 调用流水线（Pipeline）

一次 LLM 调用必须（MUST）按以下顺序被治理：
1. 路由（Routing）：决定本地/远端/具体 provider（见 `docs/specs/HYBRID_ROUTING.md`）。
2. 策略裁决（Policy）：PDP 输出 `allow|deny|require_approval`（见 `docs/specs/POLICY_DELEGATION.md`）。
3. 安全闸门（Safety Gate）：检查 `remote_calls_armed` 与 `allow_network_egress`，必要时进入 HITL。
4. 凭据获取（Secrets Broker）：如需认证，必须（MUST）通过 broker 发放短期 token（见 `docs/specs/SECRETS_BROKER.md`）。
5. 发起调用：执行网络请求或本地推理。
6. 记录证据：写入 `kind=llm_io` evidence，并在 trace 中关联（见 `docs/specs/EVIDENCE_TRACE.md`）。

### Skill 执行期结构化输出（Structured Output During Skill Execution）

当 LLM 被用于执行 skill package 时，运行时必须（MUST）满足：
- Provider 侧的结构化输出约束必须（MUST）由 runtime 自己持有；不得（MUST NOT）直接把 skill `outputs_schema` 当作 provider completion schema 透传。
- skill `outputs_schema` 必须（MUST）在 runtime 归一化后作为最终输出校验执行；若最终对象不满足 `outputs_schema`，必须（MUST）按稳定错误码失败。
- 若中间输出包含 action 数组，运行时应该（SHOULD）优先接受 canonical `operator_ref/arguments`；为兼容历史数据，也可以（MAY）读取 `skill_ref/input` 后再归一化。

### 回放（Replay）

规则（MUST）：
- 默认回放模式不得（MUST NOT）触发真实远程 LLM 请求；必须使用已记录的 `llm_io` evidence 进行重放。
- 若要在回放中允许远程请求，必须（MUST）显式开启“回放允许远程调用”开关，并再次通过安全闸门与策略裁决。

## 错误与重试（Errors/Retry）

必须（MUST）定义可枚举错误码（示例）：
- `E_LLM_DISABLED`：Provider 未启用
- `E_REMOTE_CALL_NOT_ARMED`：未武装远程调用
- `E_NETWORK_EGRESS_DENY`：egress 被沙箱/策略拒绝（见 `docs/specs/SANDBOXING.md`）
- `E_HITL_REQUIRED`：需要人工审批（见 `docs/specs/POLICY_DELEGATION.md`）
- `E_PROVIDER_AUTH_REQUIRED`：缺少认证/授权
- `E_PROVIDER_RATE_LIMIT`
- `E_PROVIDER_TIMEOUT`
- `E_PROVIDER_BAD_RESPONSE`
  - 当 Provider 能提供 HTTP 状态或响应体摘要时，错误消息必须（MUST）包含 `status` 与脱敏后的 `body_preview`，以支持本地诊断。

重试规则：
- 幂等重试必须（MUST）使用相同 `idempotency_key`。
- 对于可能产生副作用或不可重复计费的调用，默认不应（SHOULD NOT）自动重试；是否重试必须可由策略控制。
- 对于流式响应，在尚未收到任何增量输出前发生的瞬态传输错误（例如 TLS EOF、远端提前断连），Provider 可以（MAY）自动重试一次。
- 一旦已经向上游发出任意增量输出，Provider 不得（MUST NOT）自动重试同一流式请求，以避免重复或错序的用户可见内容。

## 安全与隐私（Security/Privacy）

必须（MUST）：
- 默认禁止任何远程网络访问（fail closed），除非合同（`network_egress`）声明且策略允许（见 `docs/specs/SKILL_CONTRACT.md`、`docs/specs/SANDBOXING.md`）。
- 远程 LLM 调用必须经过双重闸门：
  - 策略裁决（PDP/PEP）
  - 远程调用武装开关（Remote Call Arming）
- 明文 secrets 不得进入第三方执行环境；认证必须通过 Secrets Broker/OAuth 代持（见 `docs/specs/SECRETS_BROKER.md`）。
- `llm_io` evidence 中不得记录 access token/refresh token/API key；必须（MUST）脱敏或完全不落盘。

应该（SHOULD）：
- 对 prompts/outputs 做脱敏与最小化存储；`preview` 字段必须遵循脱敏规则（见 `docs/specs/EVIDENCE_TRACE.md`）。
- 支持数据驻留与合规策略信号，供路由与策略决策使用（见 `docs/specs/HYBRID_ROUTING.md`）。

## 可观测性（Observability）

必须（MUST）在 `kind=llm_io` evidence 中记录（可脱敏）：
- `schema_version`
- `trace_id/turn_id/span_id`
- `workspace_id`
- `provider_id`、`model_id`
- 请求摘要（消息条数、总字符数/哈希、tools 是否启用）
- 响应摘要（输出类型、tool_calls、finish_reason）
- `usage`（若可得）
- `timing`（开始/结束/耗时）
- `safety_gate` 决策摘要（armed/egress/HITL）

## 兼容与版本（Compatibility/Versioning）

- 所有 request/response/evidence 结构必须（MUST）带 `schema_version`。
- skill `outputs_schema` 的职责是最终输出校验与审计，不是 provider completion schema 的稳定形状。
- 迁移策略见 `docs/specs/VERSIONING_COMPAT.md`。

## 测试与验收（Tests/Acceptance）

必须（MUST）覆盖：
- 缺省 `remote_calls_armed=false` 时，任何远程 provider 调用都被拒绝，且错误码可审计。
- 当上层 phase 已知将调用 remote provider 时，闸门拒绝必须（MUST）发生在 phase 主执行前。
- 回放模式下不得触发真实网络请求。
- `llm_io` evidence 不包含 secrets，且 preview 经过脱敏。
- `minimax` 提供方必须（MUST）在 `MINIMAX_API_KEY` 缺失时稳定返回 `E_PROVIDER_AUTH_MISSING`。
- `minimax` 提供方必须（MUST）通过官方 OpenAI-Compatible `/chat/completions` 路径完成请求。
