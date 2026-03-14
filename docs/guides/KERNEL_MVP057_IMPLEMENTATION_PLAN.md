# Kernel MVP_057 实施方案（Implementation Plan）

- 日期（Date）：2026-03-14
- 状态（Status）：Active
- 关联 ADR（Related ADR）：
  - [ADR-0022：内核边界、资源模型与语义系统调用分层](/Users/wangwu/codex/agentos-next/docs/adrs/ADR-0022-kernel-charter-resource-model-and-semantic-syscall-layering.md)
- 关联规范（Related Specs）：
  - [MVP_057_KERNEL_CHARTER_AND_RESOURCE_MODEL](/Users/wangwu/codex/agentos-next/docs/specs/MVP_057_KERNEL_CHARTER_AND_RESOURCE_MODEL.md)
  - [MVP_050_TASK_ENVELOPE_DELIVERY_CONTRACT](/Users/wangwu/codex/agentos-next/docs/specs/MVP_050_TASK_ENVELOPE_DELIVERY_CONTRACT.md)
  - [MVP_055_KERNEL_EXECUTION_LANE_AND_TASK_AMENDMENT](/Users/wangwu/codex/agentos-next/docs/specs/MVP_055_KERNEL_EXECUTION_LANE_AND_TASK_AMENDMENT.md)

## 目的（Purpose）

把 ADR-0022 与 MVP_057 已冻结的设计边界收敛为一条可执行、可分阶段验收、可持续跟进的代码落地路径，避免实现工作重新退回“边写边定设计”状态。

## 使用方式（How To Use）

- 本文档回答“先做什么、后做什么、为什么这样排顺序”。
- 具体条目状态、目标文件、阻塞项与验收记录以
  [KERNEL_MVP057_EXECUTION_TRACKER.md](/Users/wangwu/codex/agentos-next/docs/guides/KERNEL_MVP057_EXECUTION_TRACKER.md)
  为准。
- 若实现中发现需要改变 ADR-0022 或 MVP_057 的冻结边界，必须先补 ADR / Spec，再调整本文档。

## 目标（Goals）

- 让 Kernel 的控制面（Control Plane）与执行面（Execution Plane）边界在代码中可见。
- 让 `TaskSpecV1`、`TaskContextSnapshotV1`、`ResourceBudgetV1`、`OperatorContractV1`、`SemanticSyscallV1` 逐步获得最小实现支撑。
- 让个人助理（Personal Assistant, PA）路径成为首个验证场景，而不是平行特例。
- 在不打断现有 runtime 的前提下完成 compatibility bridge，而不是一次性硬切。

## 非目标（Non-Goals）

- 本阶段不重写整个 worker runtime。
- 本阶段不要求一次性把所有 operator 都切到 semantic syscall。
- 本阶段不要求把所有应用语义模块马上迁出 `kernel/`；先明确归属，再逐步搬迁。
- 本阶段不把 ADR `Accepted` 解释为“所有代码都已完成”。

## 总体策略（Execution Strategy）

实施顺序遵循三个原则：

1. 先收紧边界，再新增抽象。
2. 先做 compatibility bridge，再切 canonical surface。
3. 先用 PA 场景验证，再扩展到更广泛 runtime surface。

因此实施切分为 4 个阶段。

## Phase 1：边界收紧与最小护栏（Boundary Hardening）

- 目标（Goal）：
  - 让现有代码显式体现 ADR-0022 中最关键的控制面约束与终态约束。
- 重点工作（Key Workstreams）：
  - `OperatorContractV1` 最小落地：至少补 `purity` 与 `visibility`，其余字段走 compatibility default。
  - `hold` delivery gate：禁止 `hold` 终态出现空 `reply_text` / 空 `deliveries`。
  - `Information Sufficiency` 入口：在 worker 侧形成 `auto_enrich / assumption_continue / need_context / leader_escalation` 的统一分流点。
  - `ResourceEscalationRequestV1` 最小协议落地。
  - Leader caller-role 先通过 internal-only API boundary 固化调用约定。
- 目标文件（Likely Files）：
  - `src/agentos_next/kernel/operator_catalog.py`
  - `src/agentos_next/kernel/task_service.py`
  - `src/agentos_next/kernel/worker_react_runtime.py`
  - `src/agentos_next/apps/pa_assistant_runtime_dispatcher.py`
  - `src/agentos_next/apps/query_gated_runtime.py`
- 阶段验收（Acceptance）：
  - `hold` 不再能静默掉用户可见交付。
  - worker 信息缺口不再只靠隐式 prompt 行为，而有显式 runtime 入口。
  - operator catalog 至少能区分 canonical / compat / internal 与 effect purity。

## Phase 2：预算与上下文归一化（Budget & Context Normalization）

- 目标（Goal）：
  - 把 `ResourceBudgetV1` 与 `TaskContextSnapshotV1` 从文档对象变成 admission/runtime 中可追踪的对象。
- 重点工作（Key Workstreams）：
  - `tool_budget / token_budget / stop_policy` 到 `ResourceBudgetV1` 的 admission 归一化。
  - `legacy_token_budget_to_compute_units(max_total_tokens)` 单点映射函数。
  - `TaskContextSnapshotV1` 的最小编译与持久化。
  - `token_estimate` 统一估算基础设施。
  - `content_hash` 的归一化和哈希实现。
- 目标文件（Likely Files）：
  - `src/agentos_next/kernel/task_service.py`
  - `src/agentos_next/kernel/execution_lane.py`
  - `src/agentos_next/kernel/context_compiler.py`
  - `src/agentos_next/kernel/prompt_compiler.py`
  - `src/agentos_next/runtime/runtime_graph*.py`
- 阶段验收（Acceptance）：
  - trace/evidence 中可看到 `ResourceBudgetV1` 和 `TaskContextSnapshotV1` 的结构化结果。
  - 旧 budget 字段仍可运行，但 admission 已有稳定归一化入口。
  - snapshot 可以区分 stale generation，并保留 `content_hash` / `token_estimate`。

## Phase 3：语义系统调用首批试点（Semantic Syscall Pilot）

- 目标（Goal）：
  - 用 memory service 验证 `SemanticSyscallV1 -> Operator` 的分层是否可运行。
- 重点工作（Key Workstreams）：
  - 新建 `syscall_registry.py` 或等价注册入口。
  - 首批 memory syscall：
    - `memory.recall`
    - `memory.persist`
    - `memory.forget`
  - reasoning surface 默认优先 syscall，raw operator 仅作为 compat surface 暴露。
  - syscall 到 operator 的 evidence 链。
- 目标文件（Likely Files）：
  - `src/agentos_next/kernel/syscall_registry.py`
  - `src/agentos_next/runtime/builtin_memory.py`
  - `src/agentos_next/skills/llm_execution.py`
  - `src/agentos_next/kernel/operator_catalog.py`
- 阶段验收（Acceptance）：
  - 至少一条 memory 路径不再直接要求模型生成 raw `builtin://memory.*` payload。
  - raw operator 与 syscall 并存时，推理面默认只看 syscall。
  - PA “记住名字/偏好”类任务通过 semantic syscall 路径可闭环。

## Phase 4：应用层归位与 PA 采用（Application Extraction & PA Adoption）

- 目标（Goal）：
  - 把 persona / 产品语义 / PA 领域对象逐步从 kernel 责任中抽离出来。
- 重点工作（Key Workstreams）：
  - 审计并迁移：
    - `src/agentos_next/kernel/soul_profile.py`
    - `src/agentos_next/kernel/agent_profile.py`
    - `src/agentos_next/kernel/prompt_compiler.py` 中与 persona/应用语义强耦合的部分
  - 引入 `application_context_ref` 的实际读写路径。
  - 在 PA 场景里明确 Program / Workstream 只属于应用层，不进入 kernel primitive。
- 目标文件（Likely Files）：
  - `src/agentos_next/apps/`
  - `src/agentos_next/kernel/soul_profile.py`
  - `src/agentos_next/kernel/agent_profile.py`
  - `src/agentos_next/kernel/prompt_compiler.py`
- 阶段验收（Acceptance）：
  - persona/沟通策略不再被误当作 kernel contract。
  - PA 多项目共享依赖场景可通过 Program + task graph 分层解释。
  - `application_context_ref` 在至少一条 PA 路径中有真实使用。

## 推荐推进顺序（Recommended Order）

1. Phase 1
2. Phase 2
3. Phase 3
4. Phase 4

不建议先做 Phase 3 或 Phase 4。原因：

- 没有 Phase 1，semantic syscall 只会叠加在不稳的边界之上。
- 没有 Phase 2，`TaskContextSnapshotV1` 和 `ResourceBudgetV1` 仍然停留在文档层。
- Phase 4 必须建立在前 3 个阶段已有稳定 kernel surface 的前提下。

## PA 验证场景（PA Validation Scenario）

以“同时推进 A/B/C 三个项目，并优先处理共享依赖 `dependency:X`”为标准场景：

- Phase 1 验证：
  - worker 发现 `dependency:X` 时，必须显式进入 `leader_escalation` 或 `hold`，而不是直接扩大写范围。
- Phase 2 验证：
  - `project_A_integration_task` 必须拥有自己的 `TaskContextSnapshotV1`，且与 `shared_resource_patch_task` 可区分 generation。
- Phase 3 验证：
  - memory / context / delivery 路径至少一条改走 semantic syscall。
- Phase 4 验证：
  - Program / Workstream 只在 PA 应用层存在，不进入 kernel primitive。

## 里程碑门（Milestone Gates）

### Gate A：Phase 1 完成

- `hold` delivery gate 已落地。
- operator contract 至少补齐 `purity` 与 `visibility`。
- worker 信息缺口有显式分流入口。

### Gate B：Phase 2 完成

- `ResourceBudgetV1` admission 归一化可观测。
- `TaskContextSnapshotV1` 可见于 trace/evidence。
- legacy budget 仍可兼容运行。

### Gate C：Phase 3 完成

- memory semantic syscall 首批闭环。
- reasoning surface 默认优先 syscall。
- PA “记住名字/偏好”路径不再依赖 raw `memory.write` payload 编造。

### Gate D：Phase 4 完成

- persona / 应用语义与 kernel contract 边界在代码目录层面有实质性收敛。
- PA 场景可用 Program + task graph + shared resource escalation 解释。

## 测试建议（Suggested Verification）

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread044_pa_polling -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_spike_memapi1_builtin_memory -v`
- Phase 2 起应补充 snapshot / budget / escalation 的定向单测。
- Phase 3 起应补充 syscall registry 与 reasoning surface hide-by-default 的定向单测。

## 退出条件（Exit Criteria）

当满足以下条件时，可以认为 ADR-0022 / MVP_057 已完成首轮落地：

- 4 个阶段全部完成，且 tracker 中无 `P0` 未完成项。
- PA 标准场景在不依赖 raw compat path 的情况下可稳定解释并运行。
- 代码、ADR、Spec、Guide 之间不存在已知的边界矛盾。
