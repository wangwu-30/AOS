# 2026-02-25 外部专家协作线程 022 (External Expert Collaboration Thread 022)

- `thread_id`: `20260225-MEMORY-EFFECT-EVAL-022`
- `status`: `round_3_completed`
- `updated_at`: `2026-02-25`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

在不替换内核的前提下，建立可复现的 A/B/C 记忆策略效果评测框架，以“对话理解准确度”作为首要决策依据。

## 范围 (In Scope)

- 三策略评测入口：A/B/C
- 统一数据集契约（JSONL）
- 统一报告契约（aggregate + per_case）
- 五指标统一口径：Relevant@1 / ConflictRate / ContextFaithfulness / OverRecallRate / UserCorrectionRate
- CLI：`mvp eval-memory`

## 非范围 (Out of Scope)

- 直接替换 AgentOS 记忆内核
- 向量检索生产化落地
- ExecuteRequest 顶层字段扩展

## 非协商约束 (Non-Negotiables)

- fail-closed 不降级
- replay-mode 不降级
- evidence/trace 可回放
- top-level API stable（policy_context only）

## 轮次进度 (Rounds)

- Round 0: 已完成（问题定义）
- Round 1: 已完成（指标口径对齐）
- Round 2: 已完成（harness contract 收敛）
- Round 3: 已完成（A/B/C runner + tests + spec）
- Round 4: 待 host 决策收口

## Evidence (Links)

- `docs/specs/MVP_022_MEMORY_EFFECT_EVAL.md`
- `src/agentos_next/evals/memory_effect_eval.py`
- `src/agentos_next/cli.py`
- `tests/test_eval_memory_effect.py`
- `docs/specs/MVP_010_MEMORY.md`
- `docs/journal/SYNTHESIS_20260225-MEMORY-EFFECT-EVAL-022.md`
- `docs/journal/DECISIONS_20260225-MEMORY-EFFECT-EVAL-022.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260225_MEMORY_EFFECT_EVAL_022_round2_cross_review.md`

