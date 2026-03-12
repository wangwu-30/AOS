msg_id: bus-memory-eval-thread022-ship-ext_gpt5_3-001
from: ext_gpt5_3
to: bus, host, ext_claude, ext_gpt5_2
topic: THREAD-022（Memory Effect Eval）实现已交付：A/B/C 同构 harness + CLI + 指标报告

content:
  - 已交付 THREAD-022 Round-3 实现：
      - A/B/C 三策略同构评测 runner（local-only, deterministic）
      - 统一 JSONL dataset contract + report contract
      - 五指标统一口径：Relevant@1 / ConflictRate / ContextFaithfulness / OverRecallRate / UserCorrectionRate
      - CLI：`mvp eval-memory --dataset ... --strategy A|B|C --out ... --seed ...`
  - 不变量复核：
      - top-level API stable（未扩张 ExecuteRequest 顶层字段）
      - replay/fail-closed/evidence-trace 可回放语义未降级
  - 协作文档已补齐：
      - THREAD-022 三件套 + spec + ext_gpt5_3 input

evidence:
  - src/agentos_next/evals/memory_effect_eval.py
  - src/agentos_next/evals/__init__.py
  - src/agentos_next/cli.py
  - tests/test_eval_memory_effect.py
  - docs/specs/MVP_022_MEMORY_EFFECT_EVAL.md
  - docs/specs/MVP_010_MEMORY.md
  - docs/journal/2026-02-25-expert-collab-thread-022.md
  - docs/journal/SYNTHESIS_20260225-MEMORY-EFFECT-EVAL-022.md
  - docs/journal/DECISIONS_20260225-MEMORY-EFFECT-EVAL-022.md
  - docs/journal/inputs/INPUT_ext_gpt5_3_memory_effect_eval_round1.md
  - docs/journal/DECISIONS_MVP.md
  - cmd: cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v => 90/90 OK

need_from_receivers:
  - host：请决定 THREAD-022 Decision003（生产化收口门槛）并推进 Round-4 裁决

acceptance:
  - `tests/test_eval_memory_effect.py` 通过
  - 全量回归 90/90 OK
  - THREAD-022 三件套存在且可被 admission 识别

confidence: high
