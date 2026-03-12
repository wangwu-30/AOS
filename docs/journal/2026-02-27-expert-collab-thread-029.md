# 2026-02-27 外部专家协作线程 029 (External Expert Collaboration Thread 029)

- `thread_id`: `20260227-BUDGET-REMOTE-LLM-CALLS-029`
- `status`: `round_3_completed`
- `updated_at`: `2026-02-27`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

为 Kernel 增加最小预算治理（Budgeting）能力：在 v1 阶段不做 token 精算，先对远程 LLM 调用次数（remote_llm_calls）做强制拦截与可回放拒绝链。

## 范围 (In Scope)

- `ExecuteRequest.budget_slice` v1 语义固定为：`remote_llm_calls`
- allow-check：
  - schema 校验（int >= 0）
  - 在 `backend=codex_oauth` 且 double-gate armed 时：budget<=0 直接拒绝
- per-call atomic decrement：
  - 每次 `CodexOAuthLLMBackend.complete_json` 调用前扣减 1
  - (N+1) 次调用必须 100% 被拦截（不触发 transport）
- perf_bench：
  - `--op budget` 作为 allow-check 开销守门（mean <= 2ms）

## 非范围 (Out of Scope)

- token 精算（P1）
- 多维资源树治理（P2）
- Remote Sandbox 端到端 budget 透传（P1）

## 非协商约束 (Non-Negotiables)

- top_level_api_stable
- fail_closed
- replay_mode_no_side_effects

## 轮次进度 (Rounds)

- Round 1: 已完成（v1 语义 + 错误码 + 实现落点）
- Round 2: 已完成（cross review + kill criteria 校验）
- Round 3: 已完成（实现 + tests + perf_bench）
- Round 4: 待 host 标记 accepted

## Evidence (Links)

- `docs/specs/MVP_029_BUDGET.md`
- `src/agentos_next/kernel/policy_engine.py`
- `src/agentos_next/llm/backend.py`
- `src/agentos_next/runtime/execute_mapping.py`
- `src/agentos_next/tools/perf_bench.py`
- `tests/test_thread029_budget_v1.py`
- `docs/journal/inputs/INPUT_thread_20260227_BUDGET_REMOTE_LLM_CALLS_029_round1.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260227_BUDGET_REMOTE_LLM_CALLS_029_round2_cross_review.md`

