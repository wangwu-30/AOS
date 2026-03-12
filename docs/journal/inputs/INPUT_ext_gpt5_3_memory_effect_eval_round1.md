id: `20260225-ext_gpt5_3-memory-effect-eval-022`
author: `ext_gpt5_3`
topic: `THREAD-022 实施输入：记忆效果优先的 A/B/C 评测落地`
position:
- 采用 A/B/C 三策略同构评测入口，先比较“理解准确度”再决定是否生产化替换。
- 保持“一切皆 Skill”主线，不在本轮引入 plugin 平台扩展点。
- 主决策门使用 `UserCorrectionRate`，护栏指标为 `ConflictRate` 与 `ContextFaithfulness`。
evidence:
- `docs/specs/MVP_022_MEMORY_EFFECT_EVAL.md`
- `src/agentos_next/evals/memory_effect_eval.py`
- `src/agentos_next/cli.py`
- `tests/test_eval_memory_effect.py`
- `docs/specs/MVP_010_MEMORY.md`
tradeoffs:
- 收益：先统一口径与可复现实验，降低“方案争论先于证据”的返工风险。
- 成本：A/B/C 都需要维护同构数据契约与报告契约。
- 风险：若样本集分布不足，指标可能高估真实对话效果；需后续扩展真实样本与开源补充集。
open_questions:
- B/C 在下一轮是否需要引入更强重排器（reranker）仍待证据支持。
- 开源数据（MultiWOZ/SGD）在本域评测中的权重比例如何设定需要 host 裁决。
proposal:
- 先按 THREAD-022 交付评测 harness 与 baseline 报告，再由 host 对 B/C 生产化路径做 Round-4 裁决。
- 若 B/C 未达到门槛，保留 A 作为默认策略并继续做治理增强。
acceptance:
- `tests/test_eval_memory_effect.py` 通过。
- `mvp eval-memory` 对 A/B/C 均可输出稳定报告。
- 线程三件套存在并可被 admission 识别。
confidence: `high`
