id: `20260216-ext_gpt5_3-008`
author: `ext_gpt5_3`
topic: `Spike-CR1 执行方案：基于 SC1 最小编译产物的 Skill-Creator discovery+compose`
position:
- 确认接手 `Spike-CR1`，并采用“最小可运行（MVP-first）”策略：先做 deterministic discovery + plan-only compose，不在 CR1 阶段直接执行计划。
- 严格复用 `SC1` 的 `Minimal schema`：以 `skillc build` 当前实际生成字段集为唯一硬依赖；`Full schema` 仅作为可选扩展示例，不进入 MVP 门禁。
- `CR1` 只负责“找什么/怎么编排”，不负责“路由到哪个模型”；模型决策由 `Spike-MR1` 与执行层策略处理，CR1 仅透传约束。
evidence:
- `tests/test_skillc_build_compiled_outputs.py`: `compiled` 目录最小验收锚点（`intent_snapshot.json`、`prompt_bundle.json`、`execution_ir.json` + `schema_version`）。
- `src/agentos_next/compiler/skillc.py`: SC1 当前编译产物与字段现实来源。
- `docs/journal/inputs/INPUT_ext_gpt5_3_skill_creator.md`: Creator 分层边界（kernel discovery 原语 vs creator 策略）既有立场。
- `docs/specs/EXECUTOR_API.md`: `compose` 输出的目标契约（对齐 `ExecuteRequest` 形状）。
tradeoffs:
- 仅消费 Minimal schema：
  - 收益：与当前实现一致，落地快、回归面最小。
  - 风险：可表达性有限；高级排序信号需后续增量引入。
- 让 CR1 直接执行组合计划：
  - 收益：端到端 demo 快。
  - 风险：与 MR1/Remote API 边界耦合，调试与归因复杂度显著升高。
open_questions:
- `compose` 产物是否在 CR1 固定为单一 JSON（例如 `compose_plan.json`），还是允许 text+json 双输出？
- deterministic 模式排序键是否先固定为 `name/version`，还是引入简单质量信号（success_rate）作为次级键？
proposal:
- Spike-CR1 分两步：
  - CR1-A（discovery）：
    - 输入：`compiled/*` 最小产物目录。
    - 输出：候选 Skill 列表（带来源路径、schema_version、基本约束摘要）。
    - 规则：未知字段忽略（forward-compatible），缺失必需文件直接拒绝并返回稳定错误码。
  - CR1-B（compose, plan-only）：
    - 输入：用户意图 + discovery 候选集。
    - 输出：可执行计划 IR（步骤序列 + 每步目标 Skill + 约束透传），形状可映射到 `ExecuteRequest`。
    - 非目标：不触发真实执行，不引入新的模型选择逻辑。
- 错误码建议（CR1 最小集）：
  - `E_CREATOR_REGISTRY_INVALID`
  - `E_CREATOR_COMPOSE_INVALID`
  - `E_CREATOR_SCHEMA_UNSUPPORTED`
- Kill criteria：
  - 若 CR1 需要把 `Full schema` 升为硬依赖才能运行，停止推进并回退到仅 discovery。
  - 若 CR1 输出无法稳定映射到 `ExecuteRequest`，停止 compose，仅保留候选检索。
acceptance:
- 兼容性：
  - 不改变现有 `mvp run-package` / `mvp exec` 输出契约与 Evidence/Trace 主字段。
- 功能性：
  - 给定同一 registry snapshot 与同一意图，discovery+compose 输出可复现（deterministic mode）。
  - compose 计划中每一步都包含可追溯的 skill 来源与约束透传字段。
- 回归：
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿。
confidence: `high`
