# MVP_029: Budget v1（remote_llm_calls）

## 目的（Purpose）

为 AgentOS Kernel 提供最小可用的资源治理原语（Resource Governance Primitive），在不引入 token 精算（Token Accounting）的前提下，先对“远程 LLM 调用次数（remote LLM calls）”做强制预算拦截（enforcement）。

## 范围（Scope）

本 spec 仅定义 v1：
- `ExecuteRequest.budget_slice` 的语义固定为：`remote_llm_calls`
- allow-check（执行前检查）与 per-call 扣减（每次调用扣减 1）
- 错误码与验收测试

不包含（Out of Scope）：
- token 精算（P1）
- 多维资源树（cpu/memory/io/net）精确治理（P2）
- Remote Sandbox 端到端预算透传（P1）

## 语义（Semantics）

### 字段（Field）

- `ExecuteRequest.budget_slice: Optional[int]`
- v1 解释：当 `policy_context.backend == "codex_oauth"` 时，表示“本次执行允许的远程 LLM 调用次数上限（remote_llm_calls）”。

### allow-check（执行前检查）

Kernel PDP/PEP 必须（MUST）在执行前做以下检查：

1. schema 校验（machine-checkable）
   - `budget_slice is None`：不启用预算限制（unlimited）
   - `budget_slice` 必须为 `int >= 0`
   - 否则拒绝：`E_BUDGET_SCHEMA_INVALID`

2. exhausted 预拒绝（pre-deny）
   - 当满足 remote LLM armed 条件：
     - `policy_context.backend == "codex_oauth"`
     - `policy_context.remote_calls_armed == true`
     - `policy_context.allow_network_egress == true`
   - 且 `budget_slice <= 0` 时，必须拒绝：`E_BUDGET_EXHAUSTED`

### per-call 扣减（每次远程 LLM 调用）

当执行路径触发远程 LLM 调用（Codex OAuth backend）时：
- 每次调用前必须原子扣减（atomic decrement）`1`
- 当剩余预算不足时必须 fail-closed：
  - 返回 `E_BUDGET_EXHAUSTED`
  - 且不得发起远程请求（no remote side effects）

## 错误码（Error Codes）

v1 MUST：
- `E_BUDGET_EXHAUSTED`
- `E_BUDGET_SCHEMA_INVALID`

## Non-Negotiables（Tokens）

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

## 实现落点（Implementation Notes）

- allow-check：`src/agentos_next/kernel/policy_engine.py`
- per-call 扣减：`src/agentos_next/llm/backend.py`（`RemoteLLMCallBudget` + `CodexOAuthLLMBackend.complete_json`）
- 映射：`src/agentos_next/runtime/execute_mapping.py` 将 `E_BUDGET_EXHAUSTED` 视为 `status=rejected`
- perf：`src/agentos_next/tools/perf_bench.py --op budget` 验证 allow-check overhead
- CLI：`mvp exec --budget-slice <int>`

## 测试与验收（Tests/Acceptance）

必须（MUST）满足：

1. 单元测试

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

2. perf_bench（连续 3 次均值达标）

```bash
PYTHONPATH=src python3 -m agentos_next.tools.perf_bench --op budget --count 1000
```

验收标准（v1）：
- allow-check mean ≤ 2ms/req
- (N+1) 拦截率 = 100%（false-negative=0）

