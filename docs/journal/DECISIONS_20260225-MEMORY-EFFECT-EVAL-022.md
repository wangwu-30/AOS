# DECISIONS: Memory Effect Eval（THREAD-022）

- `thread_id`: `20260225-MEMORY-EFFECT-EVAL-022`
- `updated_at`: `2026-02-25`
- `status`: `pending`

## Decision 001: 评测策略形态

- **状态**: `accepted`
- **结论**: 采用 A/B/C 三策略同构评测入口
  - A：baseline
  - B：ai-tutor pattern wrapper
  - C：OpenViking adapter

## Decision 002: 评测主指标

- **状态**: `accepted`
- **结论**: 采用 5 指标统一口径
  - Relevant@1
  - ConflictRate
  - ContextFaithfulness
  - OverRecallRate
  - UserCorrectionRate

## Decision 003: 生产化收口门槛

- **状态**: `pending`
- **结论**: 待 host 按报告裁决
  - 主门：UserCorrectionRate 下降
  - 护栏：ConflictRate 不升 + ContextFaithfulness 不降

## Gate

1. top-level API stable（不扩张 ExecuteRequest 顶层字段）。
2. replay/fail-closed/double-gating 不降级。
3. evidence/trace 可回放。

## Acceptance

- `tests/test_eval_memory_effect.py` 通过
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
- 线程三件套存在：
  - `docs/journal/2026-02-25-expert-collab-thread-022.md`
  - `docs/journal/SYNTHESIS_20260225-MEMORY-EFFECT-EVAL-022.md`
  - `docs/journal/DECISIONS_20260225-MEMORY-EFFECT-EVAL-022.md`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

