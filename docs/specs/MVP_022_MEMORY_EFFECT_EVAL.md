# MVP-022 记忆效果评测（Memory Effect Evaluation）

- 状态（Status）：Draft
- 日期（Date）：2026-02-25
- 目标线程（Target Thread）：`20260225-MEMORY-EFFECT-EVAL-022`
- 相关规范（Related Specs）：
  - `docs/specs/MVP_010_MEMORY.md`
  - `docs/specs/EVIDENCE_TRACE.md`
  - `docs/specs/EXECUTOR_API.md`
  - `docs/specs/VERSIONING_COMPAT.md`

## 1. 目的（Purpose）

本规范定义一个可复现实验框架，用于比较三种记忆策略（A/B/C）对“对话理解准确度”的影响。评测必须（MUST）在本地（local-only）运行，并保持回放与审计链路完整。

## 2. 范围（Scope）

MVP-022 必须（MUST）包含：
- 统一数据集契约（JSONL）
- 统一评测命令与报告契约
- 三种策略入口：A/B/C
- 五个统一指标：`Relevant@1`、`ConflictRate`、`ContextFaithfulness`、`OverRecallRate`、`UserCorrectionRate`

MVP-022 必须不包含（MUST NOT）：
- 远程检索服务依赖
- 向量数据库选型与产品化替换决策
- `ExecuteRequest` 顶层字段扩张

## 3. 不可破坏约束（Invariants）

1. 评测实现必须（MUST）保持 `ExecuteRequest` 顶层字段稳定，扩展仅允许在 `policy_context`。
2. 评测实现必须（MUST）保持 fail-closed 与 replay-mode 语义不降级。
3. 评测实现必须（MUST）保持 evidence/trace 可回放；检索过程必须有 `RETRIEVAL_CHAIN` 证据引用。

## 4. 策略定义（Strategy Definition）

- Strategy A（Baseline）：现有 `file-backed + naive search`。
- Strategy B（ai-tutor pattern wrapper）：在 A 基础上增加状态/黑名单/分层注入规则，不替换内核存储。
- Strategy C（OpenViking adapter）：分层检索适配层（local-only），不替换 AgentOS 内核。

实现要求：
- A/B/C 必须（MUST）共用同一数据集与指标计算函数。
- A/B/C 输出必须（MUST）使用同一报告 schema，保证横向可比。

## 5. 数据集契约（Dataset Contract）

数据集必须（MUST）为 JSONL；每行是一个 case 对象：

```json
{
  "case_id": "string",
  "seed_memory": [
    {
      "item_id": "string",
      "content": "string",
      "tags": ["string"],
      "ttl_seconds": 0
    }
  ],
  "query": "string",
  "labels": {
    "relevant_item_ids": ["string"],
    "conflict_item_ids": ["string"],
    "max_reasonable_hits": 5,
    "expect_correction": null
  },
  "notes": "string",
  "strategy_hints": {}
}
```

约束：
- `case_id` 必须（MUST）唯一。
- `seed_memory` 必须（MUST）非空。
- `labels.max_reasonable_hits` 必须（MUST）`>=1`。

## 6. 命令与默认值（Command & Defaults）

命令必须（MUST）提供：

```bash
agentos-next mvp eval-memory --dataset <jsonl> --strategy A|B|C [--out <json>] [--seed <int>]
```

以及（AND）：

```bash
agentos-next mvp eval-memory-compare --report-a <json> --report-b <json> --report-c <json> [--baseline-strategy A|B|C] [--guard-epsilon 0.0] [--out <json>]
```

默认值：
- `--strategy` 默认 `A`
- `--seed` 默认 `0`
- `--out` 默认不写文件，仅 stdout 输出报告
- `--baseline-strategy` 默认 `A`
- `--guard-epsilon` 默认 `0.0`

## 7. 报告契约（Report Contract）

报告必须（MUST）输出以下结构：

```json
{
  "schema_version": "1.0.0",
  "strategy": "A|B|C",
  "dataset_path": "string",
  "generated_at": "UTC ISO",
  "aggregate": {
    "relevant_at_1": 0.0,
    "conflict_rate": 0.0,
    "context_faithfulness": 0.0,
    "over_recall_rate": 0.0,
    "user_correction_rate": 0.0
  },
  "per_case": [
    {
      "case_id": "string",
      "top1_item_id": "string",
      "retrieved_item_ids": ["string"],
      "retrieval_trace_ref": "ev_...",
      "metrics": {
        "relevant_at_1": true,
        "conflict": false,
        "context_faithfulness": true,
        "over_recall": false,
        "need_correction": false
      },
      "debug": {}
    }
  ]
}
```

## 8. 指标口径（Metric Definition）

1. `Relevant@1`: `top1_item_id ∈ labels.relevant_item_ids`
2. `ConflictRate`: `top1` 或 `retrieved_item_ids` 命中 `labels.conflict_item_ids`
3. `ContextFaithfulness`:
   - 必须（MUST）存在 `retrieval_trace_ref`
   - trace 必须（MUST）存在关联 `RETRIEVAL_CHAIN` 事件
   - used evidence refs 必须（MUST）是 retrieval selected refs 的子集
4. `OverRecallRate`: `len(retrieved_item_ids) > labels.max_reasonable_hits`
5. `UserCorrectionRate`:
   - 若 `expect_correction` 有值，必须（MUST）按该标签计算
   - 否则必须（MUST）按代理规则计算：`!Relevant@1 OR Conflict`

## 9. 错误码（Error Codes）

- `E_MEMORY_EVAL_INVALID`：数据集不合法、参数非法、或评测执行失败
- `E_INPUT_SCHEMA`：case 字段形状不满足契约（可在内部转换为 `E_MEMORY_EVAL_INVALID` 对外输出）

错误路径必须（MUST）返回稳定 JSON，不得输出 traceback 到 CLI。

## 10. 边界条件（Boundary Conditions）

- 空数据集必须（MUST）失败并返回 `E_MEMORY_EVAL_INVALID`。
- case 中无可检索项时，必须（MUST）输出空检索结果并计算指标，不得崩溃。
- 每个 case 必须（MUST）使用独立 data_dir，避免样本污染。

## 11. 兼容策略（Compatibility）

- 报告 schema 仅允许加性扩展（additive change）。
- 指标键名与语义在 `schema_version=1.0.0` 下必须（MUST）稳定。
- 评测 harness 必须（MUST）保持 A/B/C 输入输出同构，避免策略间契约漂移。

## 12. 测试与验收（Tests/Acceptance）

最小验收（MUST）：
- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_eval_memory_effect.py' -v`
- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_eval_memory_compare.py' -v`

回归验收（SHOULD）：
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`

## 13. 结果比较与裁决门（Comparison & Decision Gate）

`eval-memory-compare` 的默认裁决门必须（MUST）遵循：

1. 主指标（Main Metric）：`user_correction_rate` 越低越优先。
2. 护栏（Guardrails）：
   - `conflict_rate` 不得高于 baseline（允许 `guard_epsilon` 容差）。
   - `context_faithfulness` 不得低于 baseline（允许 `guard_epsilon` 容差）。
3. 若候选策略触发护栏违规，必须（MUST）标记为 `guard_violations`，且不参与 winner 竞争。

比较输出必须（MUST）包含：
- `winner_strategy`
- `ranking`
- `guard_violations`
- `deltas_vs_baseline`
- `per_case_regressions`
