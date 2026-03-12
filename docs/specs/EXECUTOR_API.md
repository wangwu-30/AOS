# 执行器接口（Executor API）

## 目的（Purpose）

定义统一的执行器（Executor）接口，使本地执行（Local Execution）与云端沙箱执行（Remote Sandbox Execution）共享一致的语义与治理/证据能力。

## 范围（Scope）

涵盖：
- 执行请求/响应接口
- 幂等（Idempotency）、取消（Cancellation）、超时（Timeout）、重试（Retry）
- evidence/trace correlation

不涵盖：具体沙箱实现细节（见 `SANDBOXING.md`）。

## 核心概念（Concepts）

见 `docs/glossary.md`：编排器（Orchestrator）、执行器（Executor）、证据（Evidence）、追踪（Trace）、工作区（Workspace）。

## 接口/数据结构（Interfaces/Data）

### ExecuteRequest（执行请求）

必须（MUST）包含字段：
- `workspace_id`：工作区（Workspace）标识
- `operator_ref`：操作符引用（Operator Reference，可以是内容寻址 ref、registry ref 或 `builtin://...`）
- `arguments`：结构化参数
- `idempotency_key`：幂等键（Idempotency Key）
- `deadline_ms`：截止时间（软/硬超时由实现定义但必须记录）
- `trace`：关联信息：`trace_id`、`turn_id`、`parent_span_id`
- `policy_context`：策略上下文（含 delegation token、user override）

可以（MAY）包含字段：
- `preferred_target`：`local|remote|auto`
- `priority`：优先级
- `budget_slice`：预算切片（v1 语义见 `docs/specs/MVP_029_BUDGET.md`）

约束（MUST）：
- `ExecuteRequest` 顶层不得（MUST NOT）新增 task-specific timeout/retry 字段；`task_execution_policy_v1` 必须（MUST）通过 `policy_context` 投影。
- `deadline_ms` 必须（MUST）保留，但只作为兼容 hard cap / root fallback；task 级 timeout/retry 应该（SHOULD）由 `policy_context.task_execution_policy` 驱动。

### ExecuteResult（执行结果）

必须（MUST）包含字段：
- `status`：`accepted|rejected|failed|canceled|timeout`
- `evidence_refs`：Evidence 引用列表（refs）
- `artifact_refs`：可选的产物 refs
- `error_code`：错误码（失败/拒绝时）
- `timing`：p50/p95 统计由系统汇总，但单次必须记录 `started_at/ended_at`

## 语义与状态机（Semantics/State Machine）

执行器必须（MUST）支持：
- 幂等：相同 `idempotency_key` 的重复请求不得产生重复副作用；必须返回同一结果或等价结果。
- 取消：取消后仍要记录已有的 tool/evidence，但不得继续产生新副作用。
- correlation：同一次执行的子步骤 evidence 必须可串到同一 `trace_id`。
- 当上层 runtime 把预算耗尽解释为 `hold/HITL_REQUIRED` 时，执行器可以（MAY）正常返回已完成步骤结果；不得（MUST NOT）自行把 hold 改写成成功或硬失败。

## 错误与重试（Errors/Retry）

错误码必须（MUST）来自统一枚举（待在 `EVIDENCE_TRACE.md` 补齐）：
- `E_POLICY_DENY`
- `E_HITL_REQUIRED`
- `E_CYCLE_DETECTED`
- `E_SANDBOX_DENY`
- `E_UPSTREAM_RETRY_EXHAUSTED`
- `E_TIMEOUT`
- `E_EXECUTION_FAILED`
- `E_HITL_REQUIRED`

## 安全与隐私（Security/Privacy）

- 执行器必须（MUST）在执行入口作为策略执行点（PEP），强制策略与委托约束。
- 当 PEP 给出 `deny|ask` 时，执行器必须（MUST）返回稳定错误码，并写入 `kind=policy|error` evidence 与 `POLICY_DECIDED|ERROR` trace 事件。
- 第三方执行不得直接接触明文 secrets（见 `SECRETS_BROKER.md`）。
- 若实现将 `workspace_id`、`idempotency_key` 等标识落盘为文件路径，必须（MUST）先做路径安全归一化（sanitize/hash），禁止（MUST NOT）直接拼接原始输入形成路径段，且最终路径必须位于实现定义的数据根目录内。
- 当 `policy_context.task_execution_policy.side_effect_safe_retry=false` 时，执行器或其上层调用者不得（MUST NOT）对非幂等 action 自动重试。

兼容策略（Compatibility Strategy）：
- 运行时可以（MAY）在内存结构中保留 `skill_ref/input` 只读别名，用于历史记录回放或向后兼容。
- 新写入的 active runtime surfaces 必须（MUST）统一使用 `operator_ref/arguments`，不得继续新写入 `skill_ref/input`。

## 可观测性（Observability）

必须（MUST）记录：
- 执行阶段状态
- 所有工具调用的 started/finished
- 路由决策与 override
- task 级 timeout/retry 生效值
- `runtime_role=leader|worker`（若上层提供）

## 兼容与版本（Compatibility/Versioning）

见 `VERSIONING_COMPAT.md`。

## Spike-005A 入口语义（Spike-005A Entrypoint Semantics）

- 系统可以（MAY）提供编排器（Orchestrator）到执行器（Executor）的新入口（例如库入口或 `mvp exec` CLI），该入口必须（MUST）返回 `ExecuteResult` 语义。
- 新入口默认值（Default）必须（MUST）为：
  - `preferred_target=local`
  - `status` 从底层执行结果映射为 `accepted|rejected|failed|canceled|timeout`
  - `artifact_refs=[]`（当底层未产生产物时）
- 新入口错误码必须（MUST）复用既有稳定错误码（stable error code），至少包含 `E_HITL_REQUIRED`、`E_TIMEOUT`、`E_EXECUTION_FAILED`；不得引入同语义多错误码（duplicate semantic codes）。
- 边界条件（Boundary Conditions）必须（MUST）满足：
  - 当底层执行拒绝时，`status=rejected` 且 `error_code` 非空。
  - 当底层执行成功时，`status=accepted` 且 `error_code=null`。
  - 当 evidence 时间戳缺失时，`timing.started_at/ended_at` 仍必须（MUST）为可解析 UTC ISO 时间。
- 兼容策略（Compatibility Strategy）必须（MUST）满足：
  - `mvp run-package` 既有 JSON 输出字段与字段语义必须（MUST）保持不变。
  - 新入口不得（MUST NOT）破坏 `evidence_refs` 与 trace 落盘路径约定。
- 测试与验收必须（MUST）覆盖：
  - 新入口成功路径与拒绝路径（至少 1 个 `E_HITL_REQUIRED` 用例）。
  - `mvp run-package` 输出字段回归（字段集合与错误码语义稳定）。

## 测试与验收（Tests/Acceptance）

- 在 `local` 与 `remote` 执行相同 skill，必须能生成可串联的 trace，并可回放。
- 相同 `idempotency_key` 重放不产生重复副作用。
