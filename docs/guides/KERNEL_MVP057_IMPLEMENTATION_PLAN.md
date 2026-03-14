# Kernel MVP_057 实施方案（Implementation Plan）

- 日期（Date）：2026-03-14
- 状态（Status）：Active
- 安全回退点（Safety Checkpoint）：
  - `47c850e` `runtime: land kernel charter docs and PA hold fixes`
- 关联 ADR（Related ADR）：
  - [ADR-0022：内核边界、资源模型与语义系统调用分层](/Users/wangwu/codex/agentos-next/docs/adrs/ADR-0022-kernel-charter-resource-model-and-semantic-syscall-layering.md)
- 关联规范（Related Specs）：
  - [MVP_057_KERNEL_CHARTER_AND_RESOURCE_MODEL](/Users/wangwu/codex/agentos-next/docs/specs/MVP_057_KERNEL_CHARTER_AND_RESOURCE_MODEL.md)
  - [MVP_050_TASK_ENVELOPE_DELIVERY_CONTRACT](/Users/wangwu/codex/agentos-next/docs/specs/MVP_050_TASK_ENVELOPE_DELIVERY_CONTRACT.md)
  - [MVP_055_KERNEL_EXECUTION_LANE_AND_TASK_AMENDMENT](/Users/wangwu/codex/agentos-next/docs/specs/MVP_055_KERNEL_EXECUTION_LANE_AND_TASK_AMENDMENT.md)

## 目的（Purpose）

把 ADR-0022 与 MVP_057 已冻结的设计边界直接落成代码中的唯一 canonical V1 主路径。

## 使用方式（How To Use）

- 本文档回答“按什么顺序重构、为什么这么排、阶段门是什么”。
- 具体条目状态、目标文件与验收记录以
  [KERNEL_MVP057_EXECUTION_TRACKER.md](/Users/wangwu/codex/agentos-next/docs/guides/KERNEL_MVP057_EXECUTION_TRACKER.md)
  为准。
- 若实现中发现需要改变 ADR-0022 或 MVP_057 的冻结边界，必须先补 ADR / Spec，再调整本文档。

## 核心目标（Goals）

- 一次性把 canonical V1 数据结构落地为代码中的唯一路径。
- 让 `ResourceBudgetV1`、`OperatorContractV1`、`TaskContextSnapshotV1`、`AssumptionEvidenceV1`、`ResourceEscalationRequestV1` 成为真实代码对象，而不是文档占位。
- 删除 `tool_budget / token_budget / stop_policy / time_budget_ms` 等旧字段在 runtime 主路径中的继续存在。
- 统一 `completion_contract_ref -> acceptance_contract_ref` 命名。
- 让 PA 场景成为首个验证场景，而不是重构完成后的附带测试。

## TaskSpec 切换映射（TaskSpec Cutover Mapping）

| 旧字段 / 旧对象 | 新字段 / 新对象 | 处理方式 |
| --- | --- | --- |
| `tool_budget` | `resource_budget` | Phase 1 直接删除并合并入 `ResourceBudgetV1` |
| `token_budget` | `resource_budget` | Phase 1 直接删除并合并入 `ResourceBudgetV1` |
| `stop_policy.deadline_ms` | `resource_budget.time_budget_ms` | Phase 1 合并到 `ResourceBudgetV1` |
| `time_budget_ms` | `resource_budget.time_budget_ms` | Phase 1 合并到 `ResourceBudgetV1` |
| `completion_contract_ref` | `acceptance_contract_ref` | Phase 1 直接重命名 |
| `task_execution_policy` | 不进入 `TaskSpecV1` | Phase 1 从 `TaskSpec / TaskRecord / TaskExecutionNode` 移出；行为策略迁移到 `ExecutionLaneProfile` 或等价 `WorkerRuntimeConfig` |
| 无 | `missing_inputs` | Phase 1 新增 |
| 无 | `context_strategy` | Phase 1 新增 |
| 无 | `max_escalation_count` | Phase 1 新增 |
| 无 | `application_context_ref` | Phase 3 接入真实使用路径 |

说明（Notes）：

- `task_execution_policy` 当前在代码中是 `dict[str, Any]`，更接近运行时行为策略，而不是资源限额；它不应进入 `ResourceBudgetV1`。
- `StopPolicy.no_progress_window / max_repeated_action_fingerprint_hits / continue_until_terminal` 等字段与 `task_execution_policy` 一样，属于行为策略，当前计划迁入 `ExecutionLaneProfile` 或等价 `WorkerRuntimeConfig`，不进入 `ResourceBudgetV1`。

## 非目标（Non-Goals）

- 本阶段不重写整个 worker runtime。
- 本阶段不要求一次性把所有 operator 都切到 semantic syscall。
- 本阶段不要求一次性把所有应用语义模块都迁出 `kernel/`。
- 旧 budget 字段将在切换时直接删除。
- 本阶段若遇到旧 JSON / 持久化数据无法反序列化，优先通过 migration script 或手动清理解决，不做运行时 fallback。

## 总体策略（Execution Strategy）

实施顺序遵循三个原则：

1. 先 commit 当前状态，再大刀阔斧重构。
2. 直接定义 canonical V1 dataclass，旧字段一次性替换。
3. 先用 PA 场景验证，再扩展到更广泛 runtime surface。

因此实施切分为 `Phase 0 + Phase 1 + Phase 2 + Phase 3`。

## Phase 0：安全点与类型冻结（Safety Checkpoint & Type Freeze）

- 目标（Goal）：
  - 先固定安全回退点，再一次性冻结 canonical V1 类型。
- 当前状态（Current State）：
  - 安全回退点 commit `47c850e` 已完成。
  - canonical V1 类型冻结已完成，类型入口位于 `src/agentos_next/kernel/types.py`。
- 重点工作（Key Workstreams）：
  - 在 `src/agentos_next/kernel/types.py` 或等价 canonical 类型文件中定义：
    - `ResourceBudgetV1`
    - `ResourceCostVectorV1`
    - `OperatorContractV1`
    - `TaskSpecV1`
    - `TaskContextSnapshotV1`
    - `AssumptionEvidenceV1`
    - `ResourceEscalationRequestV1`
- 目标文件（Likely Files）：
  - `src/agentos_next/kernel/types.py`
- 阶段验收（Acceptance）：
  - 所有 V1 类型均可从单一 canonical 类型入口导入。
  - 不再需要在多个模块各自重复定义 V1 结构。

## Phase 1：Canonical V1 直接切换（Canonical Cutover）

- 目标（Goal）：
  - 把内核主路径一次性切到 canonical V1 数据结构，旧字段直接替换。
- 重点工作（Key Workstreams）：
  - `ResourceBudgetV1` 替换旧 budget 字段：
    - 删除 `TaskSpec / TaskRecord / TaskExecutionNode` 中的
      `tool_budget / token_budget / stop_policy / time_budget_ms`
    - 删除 `execution_lane.py` 中的 `TokenBudget / StopPolicy` 旧类与相关 helper
    - 引入 `default_resource_budget_for_lane(lane)` 或等价入口
    - 把 `StopPolicy.no_progress_window / max_repeated_action_fingerprint_hits / continue_until_terminal` 等行为策略迁移到 `ExecutionLaneProfile` 或等价 `WorkerRuntimeConfig`
    - 把 `completion_contract_ref` 统一重命名为 `acceptance_contract_ref`
  - `OperatorContractV1` 完整落地：
    - `_catalog_entries()` 改为返回结构化 contract，而不是 raw dict
    - 所有字段显式填写，不依赖运行时推断
  - `TaskContextSnapshotV1` 直接落地：
    - 在 `context_compiler.py` 实现 `compile_snapshot(...)`
    - 落实 `content_hash` 与 `token_estimate`
    - `token_estimate` 首版使用 `len(text) // 4` 或等价 heuristic，不依赖外部 tokenizer
  - 落地 Phase 1 运行时护栏：
    - `hold` delivery gate
    - `resolve_information_gap(...)` 或等价入口
    - `ResourceEscalationRequestV1` runtime path
- 目标文件（Likely Files）：
  - `src/agentos_next/kernel/types.py`
  - `src/agentos_next/kernel/task_service.py`
  - `src/agentos_next/kernel/task_execution_graph.py`
  - `src/agentos_next/kernel/execution_lane.py`
  - `src/agentos_next/kernel/operator_catalog.py`
  - `src/agentos_next/kernel/context_compiler.py`
  - `src/agentos_next/kernel/prompt_compiler.py`
  - `src/agentos_next/kernel/worker_react_runtime.py`
  - `src/agentos_next/apps/pa_assistant_runtime_dispatcher.py`
  - `src/agentos_next/apps/query_gated_runtime.py`
  - `tests/`
- 阶段验收（Acceptance）：
  - `src/agentos_next/` 主路径中不再保留 `tool_budget / token_budget / stop_policy`。
  - operator catalog 不再使用 raw dict entry 作为主 contract。
  - snapshot 可以被构造、序列化、反序列化，并带 `content_hash`。
  - `hold` 不再能静默掉用户可见交付。
  - worker 信息缺口有显式 runtime 分流入口。

## Phase 2：语义系统调用首批试点（Semantic Syscall Pilot）

- 目标（Goal）：
  - 用 memory service 验证 `SemanticSyscallV1 -> OperatorContractV1` 的分层。
- 重点工作（Key Workstreams）：
  - 新建 `syscall_registry.py` 或等价注册入口。
  - 首批 memory syscall：
    - `memory.recall`
    - `memory.persist`
    - `memory.forget`
  - reasoning surface 默认优先 syscall。
  - syscall 到 operator 的 evidence 链。
- 目标文件（Likely Files）：
  - `src/agentos_next/kernel/syscall_registry.py`
  - `src/agentos_next/runtime/builtin_memory.py`
  - `src/agentos_next/skills/llm_execution.py`
  - `src/agentos_next/kernel/operator_catalog.py`
- 阶段验收（Acceptance）：
  - 至少一条 memory 路径不再要求模型直接构造 raw `builtin://memory.*` payload。
  - 推理面默认优先 syscall，不优先 raw operator。
  - PA “记住名字/偏好”场景通过 semantic syscall 闭环。

## Phase 3：应用层归位与 PA 采用（Application Extraction & PA Adoption）

- 目标（Goal）：
  - 把 persona / 产品语义 / PA 领域对象逐步从 kernel 责任中抽离出来。
- 重点工作（Key Workstreams）：
  - 审计并迁移：
    - `src/agentos_next/kernel/soul_profile.py`
    - `src/agentos_next/kernel/agent_profile.py`
    - `src/agentos_next/kernel/prompt_compiler.py` 中与 persona/应用语义强耦合的部分
  - 引入 `application_context_ref` 的真实读写路径。
  - 在 PA 场景里明确 Program / Workstream 只属于应用层，不进入 kernel primitive。
- 目标文件（Likely Files）：
  - `src/agentos_next/apps/`
  - `src/agentos_next/kernel/soul_profile.py`
  - `src/agentos_next/kernel/agent_profile.py`
  - `src/agentos_next/kernel/prompt_compiler.py`
- 阶段验收（Acceptance）：
  - persona/沟通策略不再被误当作 kernel contract。
  - `application_context_ref` 在至少一条 PA 路径中有真实使用。
  - PA 多项目共享依赖场景可用 Program + task graph 分层解释。

## 推荐推进顺序（Recommended Order）

1. `Phase 0`
2. `Phase 1`
3. `Phase 2`
4. `Phase 3`

Phase 1 内部建议顺序：

1. 全局旧字段替换为 `ResourceBudgetV1`
2. `OperatorContractV1` 完整 dataclass 化
3. `TaskContextSnapshotV1`
4. `hold` delivery gate
5. `resolve_information_gap(...)`
6. `ResourceEscalationRequestV1`

## PA 验证场景（PA Validation Scenario）

以“同时推进 A/B/C 三个项目，并优先处理共享依赖 `dependency:X`”为标准场景：

- Phase 1 验证：
  - worker 发现 `dependency:X` 时，必须显式进入 `leader_escalation` 或 `hold`，而不是直接扩大写范围。
  - `project_A_integration_task` 必须拥有自己的 `TaskContextSnapshotV1`。
- Phase 2 验证：
  - memory / context / delivery 路径至少一条改走 semantic syscall。
- Phase 3 验证：
  - Program / Workstream 只在 PA 应用层存在，不进入 kernel primitive。

## 里程碑门（Milestone Gates）

### Gate 0：Phase 0 完成

- canonical V1 dataclass 已冻结到单一类型入口。
- 安全回退点已存在且可用。

### Gate A：Phase 1 完成

- `ResourceBudgetV1` 完成一次性切换。
- operator catalog 完成完整 contract 化。
- `TaskContextSnapshotV1`、`AssumptionEvidenceV1`、`ResourceEscalationRequestV1` 在 runtime 中有真实入口。
- `hold` delivery gate 已落地。

### Gate B：Phase 2 完成

- memory semantic syscall 首批闭环。
- 推理面默认优先 syscall。
- PA “记住名字/偏好”路径不再依赖 raw `memory.write` payload。

### Gate C：Phase 3 完成

- persona / 应用语义与 kernel contract 边界在代码目录层面有实质性收敛。
- PA 场景可用 Program + task graph + shared resource escalation 解释。

## 风险与缓解（Risks & Mitigations）

- 风险：旧字段被一次性删除后，现有 JSON 持久化数据无法读取。
  - 缓解：以 `47c850e` 作为回退点；必要时补 migration script 或手动清理。
- 风险：test 大面积变红。
  - 缓解：这是预期行为；先完成 canonical cutover，再批量修 test。
- 风险：其他内部调用点仍依赖旧字段。
  - 缓解：当前没有独立外部消费者，直接全局搜索替换比保留旧路径更便宜。

## 测试建议（Suggested Verification）

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread044_pa_polling -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_spike_memapi1_builtin_memory -v`
- Phase 1 起应补充旧字段删除后的定向单测。
- Phase 2 起应补充 syscall registry 与 reasoning surface 的定向单测。

## Spec 同步修改（Spec Updates Required）

当前实施方案选择“代码侧直接切 canonical V1 主路径”，因此在 `Phase 1` 合并前，以下规范条目必须同步收敛：

- [MVP_057_KERNEL_CHARTER_AND_RESOURCE_MODEL.md](/Users/wangwu/codex/agentos-next/docs/specs/MVP_057_KERNEL_CHARTER_AND_RESOURCE_MODEL.md) 中 `Migration Mapping` 一节：
  - 从“并存归一化”改为“直接替换 + migration script / 手动清理”
- [MVP_057_KERNEL_CHARTER_AND_RESOURCE_MODEL.md](/Users/wangwu/codex/agentos-next/docs/specs/MVP_057_KERNEL_CHARTER_AND_RESOURCE_MODEL.md) 中 `Compatibility/Versioning` 一节：
  - 删除对内部 runtime 主路径的 compatibility bridge 要求
  - 若未来需要面对外部消费者的兼容承诺，应另起独立规范，而不是继续压在当前内核实现计划里

当前选择（Decision）：

- 本轮实施以代码和规范同步收敛为准，不保留“代码直接替换、spec 继续要求并存”的双口径状态。

## 退出条件（Exit Criteria）

当满足以下条件时，可以认为 ADR-0022 / MVP_057 已完成首轮落地：

- `Phase 0` 到 `Phase 3` 全部完成，且 tracker 中无 `P0` 未完成项。
- PA 标准场景在只经过 canonical V1 主路径的情况下可稳定解释并运行。
- 代码、ADR、Spec、Guide 之间不存在已知的边界矛盾。
