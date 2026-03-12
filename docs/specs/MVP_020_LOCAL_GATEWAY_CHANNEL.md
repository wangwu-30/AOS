# MVP-020 本地网关通道（Local Gateway Channel）

- 状态（Status）：Accepted
- 日期（Date）：2026-02-25
- 目标 Spike（Target Spike）：CH1
- 相关规范（Related Specs）：
  - `docs/specs/EXECUTOR_API.md`
  - `docs/specs/MVP_011_ASSISTANT_LOOP.md`
  - `docs/specs/MVP_012_SCHEDULER.md`
  - `docs/specs/REMOTE_SANDBOX_API.md`
  - `docs/specs/VERSIONING_COMPAT.md`

## 1. 目的（Purpose）

定义 CH1 的最小本地网关通道（Local Gateway Channel）规范：使用 HTTP 请求把消息映射为 `ExecuteRequest`，复用现有 Orchestrator/Executor 执行链路，并保持 `channel-stdio` 稳定输出契约语义等价。

## 2. 范围（Scope）

MVP-020 必须（MUST）提供：
- `mvp channel-http` 命令
- HTTP 路径：`POST /v1/channel/messages`
- 无状态会话模型（stateless-by-trace）
- 与 `channel-stdio` 等价的稳定响应键集合

MVP-020 必须不包含（MUST NOT）：
- WebSocket / SSE
- daemon session cache
- ExecuteRequest 顶层字段扩张
- 远程默认放开（double-gating/replay-mode 不得降级）

## 3. 传输与默认值（Transport & Defaults）

- 传输：HTTP-only（P0）
- 默认监听：`127.0.0.1`（loopback）
- 默认端口：`8765`
- 默认目标：`auto`
- 默认 `workspace_id`：`local`
- 默认 `deadline_ms`：`60000`
- 鉴权（Auth）默认：`none`（仅限 loopback）
- 限流（Rate Limit）默认：`off`

## 3.1 A/A/A 裁决冻结（Decision Freeze）

- Decision001（A）：P0 仅 HTTP-only。
- Decision002（A）：P0 会话语义为 stateless-by-trace（服务端不缓存会话状态）。
- Decision003（A）：P0 采用最小门禁（`auth=none@localhost` + `rate_limit=off`）；token auth 与 rate limit 进入后续 bounded spike。

## 4. 请求与响应契约（Request/Response Contract）

### 4.1 请求（Request）

`POST /v1/channel/messages` body 必须（MUST）是 JSON object。

最小字段：
- `message`（string）或 `arguments`（object）二选一

可选字段：
- `idempotency_key`（string）
- `trace_id` / `turn_id` / `span_id` / `parent_span_id`（string）
- `workspace_id`（string）
- `operator_ref`（string）
- `preferred_target`（`auto|local|remote`）
- `policy_context`（object）
- `model`（string）

兼容策略（Compatibility）：
- 为兼容历史调用，请求体可以（MAY）读取 `skill_ref/input` 作为只读别名。
- 网关映射到 `ExecuteRequest` 时必须（MUST）统一落为 `operator_ref/arguments`。

### 4.2 响应（Response）

响应键集合必须（MUST）与 `channel-stdio` 稳定集合对齐：
- `ok`
- `status`
- `error_code`
- `trace_id`
- `turn_id`
- `span_id`
- `evidence_refs`
- `artifact_refs`

错误路径必须（MUST）返回稳定 JSON，不得输出 traceback。

## 5. 策略边界（Policy Boundary）

HTTP 请求中的 `policy_context` 视为不可信输入。治理键必须（MUST）由服务端覆盖（默认 false）：
- `remote_calls_armed`
- `allow_network_egress`
- `approved_by_human`
- `replay_mode`

扩展字段仍可通过 `policy_context` 透传，但不得（MUST NOT）突破上述治理键覆盖语义。

## 6. 语义与幂等（Semantics & Idempotency）

- 会话模型：stateless-by-trace（服务端不维护会话缓存）
- 幂等：相同 `workspace_id + idempotency_key` 必须复用已有结果（依赖 Orchestrator idempotency store）
- P0 并发策略：单线程处理（single-thread）优先，避免并发窗口导致重复执行

## 7. 错误码（Error Codes）

- 输入错误：`E_BAD_CHANNEL_INPUT`（或兼容 `E_INPUT_SCHEMA`）
- 执行兜底：`E_EXECUTION_FAILED`
- 业务错误：沿用 ExecuteResult.error_code（如 `E_TIMEOUT`、`E_HITL_REQUIRED`、`E_REPLAY_REMOTE_DISABLED`）

## 8. 兼容策略（Compatibility）

- 必须（MUST）保持 ExecuteRequest 顶层字段稳定
- 必须（MUST）保持 `channel-stdio` 已有行为与测试通过
- 新增能力优先以 additive 方式引入（新增命令/新增 spec，不改旧契约）

## 9. 测试与验收（Tests/Acceptance）

最小测试矩阵（MUST）：
1. happy path：返回稳定键集合，trace/evidence 落盘
2. invalid body/json：稳定错误 JSON（无 traceback）
3. model override：`policy_context["model"]` 生效
4. idempotency：重复请求不重复追加 trace
5. replay-mode：远程副作用被阻断（错误码稳定）

验收命令：
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_ch1_local_gateway.py' -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
