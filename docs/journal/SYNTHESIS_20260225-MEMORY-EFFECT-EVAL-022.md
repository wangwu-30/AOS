# SYNTHESIS: Memory Effect Eval（A/B/C）

- `thread_id`: `20260225-MEMORY-EFFECT-EVAL-022`
- `updated_at`: `2026-02-25`
- `status`: `resolved`

## 综合结论

- 已落地最小可复现评测 harness：
  - Strategy A：当前 `file-backed + naive search`
  - Strategy B：ai-tutor pattern wrapper（规则增强）
  - Strategy C：OpenViking adapter（local-only）
- 三策略共享同一数据集与报告契约，支持横向效果比较。
- 评测口径统一为 5 指标，并输出 aggregate/per_case 双层报告。

## 关键收敛点

- 保持“一切皆 Skill”的执行主线：A/B/C 仅作为评测策略，不引入 platform plugin 系统。
- 不改 ExecuteRequest 顶层字段；扩展仍在 `policy_context`。
- 每个 case 独立 data_dir，避免样本污染并保证回放可审计。

## Gate（通过条件）

1. `mvp eval-memory` 可稳定输出 JSON 报告。
2. `ContextFaithfulness` 计算必须依赖 retrieval evidence + trace event。
3. A/B/C 必须同构输入输出，不得策略漂移。

## 验收锚点

- `tests/test_eval_memory_effect.py`
- `docs/specs/MVP_022_MEMORY_EFFECT_EVAL.md`
