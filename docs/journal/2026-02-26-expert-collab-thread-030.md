# 2026-02-26 外部专家协作线程 030 (External Expert Collaboration Thread 030)

- `thread_id`: `20260226-CAPABILITY-SCHEMA-030`
- `status`: `round_3_completed`
- `updated_at`: `2026-02-26`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

将“权限最小化（Least Privilege）”固化为 Kernel 级治理原语：所有高权限/高风险能力必须通过显式 capability 句柄声明，PEP 默认拒绝（default deny），并提供可审计的拒绝理由与错误码。

## 范围 (In Scope)

- `policy_context.capabilities[]` schema（machine-checkable）
- Kernel PEP enforce（缺能力 => deny）
- 错误码冻结：
  - `E_CAPABILITY_DENY`
  - `E_CAPABILITY_SCHEMA_INVALID`
  - `E_HITL_REQUIRED`（复用，不新增同义码）
- v1 required capability mapping（builtin + remote intents）

## 非范围 (Out of Scope)

- capability delegation graph / minted tokens（P1）
- 细粒度 scope=skill 的强约束执行（P1）
- 动态 capability 申请（P1）

## 非协商约束 (Non-Negotiables)

- top-level API stable（不新增 ExecuteRequest 顶层字段；扩展仅 policy_context）
- fail-closed 不降级
- replay-mode 无新增副作用（拒绝路径必须稳定 error_code + evidence + trace）

## 轮次进度 (Rounds)

- Round 0: 已完成（scope/错误码冻结）
- Round 1: 已完成（schema + required mapping）
- Round 2: 已完成（cross-review marker + admission MUST）
- Round 3: 已完成（实现 + tests + 回归）
- Round 4: 待 host 标记 accepted

## Evidence (Links)

- `docs/specs/MVP_030_CAPABILITY_SCHEMA.md`
- `src/agentos_next/kernel/capabilities.py`
- `src/agentos_next/kernel/policy_engine.py`
- `tests/test_thread030_capability_schema.py`
- `docs/journal/inputs/INPUT_thread_20260226_CAPABILITY_SCHEMA_030_round1.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260226_CAPABILITY_SCHEMA_030_round2_cross_review.md`

