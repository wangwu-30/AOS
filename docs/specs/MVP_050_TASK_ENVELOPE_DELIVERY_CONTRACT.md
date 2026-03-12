# MVP_050_TASK_ENVELOPE_DELIVERY_CONTRACT

- 状态（Status）：Draft
- 日期（Date）：2026-03-07
- 目标版本（Target）：MVP_050
- 相关规范（Related Specs）：
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_014_DIALOG_STATE_MACHINE.md`
  - `docs/specs/MVP_010_MEMORY.md`
  - `docs/specs/MVP_018_SELF_IMPROVEMENT_LOOP.md`
  - `docs/specs/MVP_046_AGENT_AXIOMS_CONTEXT_PLANES.md`
  - `docs/specs/EVIDENCE_TRACE.md`

## 目的（Purpose）

定义“任务信封（Task Envelope）+ 交付合同（Delivery Contract）”的最小规范，使运行时把原始输入编译为可执行任务对象，并以验收驱动闭环与可见进度状态交付结果。

## 范围（Scope）

本规范覆盖：
- `TaskEnvelopeV1` 的最小字段与编译语义。
- `DeliveryContractV1` 的 done/verify/repair 语义。
- `ProgressEventV1` 的用户可见生命周期。
- `TaskBundleV1` 与 `TaskExecutionPolicyV1` 对 TaskEnvelope/DeliveryContract 的绑定语义。
- 检索优先（retrieval-first）、验收驱动（acceptance-driven）、失败沉淀（failure distillation）的最小约束。

本规范不覆盖：
- 具体 LLM 提示词模板。
- UI 呈现样式。
- 具体 memory backend、vector store 或 ranking 算法实现。

## 核心原则（Principles）

- 代理必须（MUST）首先被视为任务系统（Task System），而不是聊天机器人。
- 原始输入不得（MUST NOT）直接作为执行模型的最终输入；运行时必须（MUST）先将其编译为 `TaskEnvelopeV1`。
- 运行时必须（MUST）只有一个规范任务入口（Canonical Task Ingress）；CLI、Scheduler、Polling、Channel、HTTP 等只能作为提交适配器（Submitter Adapter）接入。
- 外部结果面必须（MUST）通过消费适配器（Consumer Adapter）消费交付状态与结果，不得绕过交付验证直接对外宣布成功。
- 交付完成必须（MUST）由 `DeliveryContractV1` 验证，而不是由模型自我宣告。
- 长对话应该（SHOULD）通过任务状态更新驱动，而不是通过无限累积 transcript 驱动。
- 当任务与既有事实、历史失败、用户偏好或已有工件相关时，运行时必须（MUST）先检索，再决定是否写入新记忆。
- 复杂任务必须（MUST）向用户暴露 `ack -> progress -> blocker -> done` 的可见过程。

## 接口/数据结构（Interfaces/Data）

### TaskEnvelopeV1（MUST）

```json
{
  "schema_version": "1.0.0",
  "task_id": "string",
  "objective": "string",
  "deliverable": "string",
  "acceptance_criteria": ["string"],
  "constraints": ["string"],
  "source_inputs": [
    {
      "kind": "user_message|event|schedule|system",
      "ref": "string|null",
      "summary": "string"
    }
  ],
  "known_facts": ["string"],
  "open_questions": ["string"],
  "ambiguity_policy": "clarify_if_blocking|minimize_questions",
  "retrieval_hints": ["string"]
}
```

默认值（MUST）：
- `schema_version = "1.0.0"`
- `deliverable = "user_visible_answer"`
- `constraints = []`
- `source_inputs = []`
- `known_facts = []`
- `open_questions = []`
- `ambiguity_policy = "clarify_if_blocking"`
- `retrieval_hints = []`

约束（MUST）：
- `objective` 不得（MUST NOT）为空。
- `acceptance_criteria` 长度必须（MUST）在 `1..16`；若原始输入未显式给出，编译器必须（MUST）生成最小可验收标准。
- `source_inputs` 长度应该（SHOULD）在 `1..8`；不得包含无裁剪的长 transcript。
- `TaskEnvelopeV1` 不得（MUST NOT）承担长期状态存储职责；历史正文必须通过 evidence/memory 引用或摘要进入。

### DeliveryContractV1（MUST）

```json
{
  "schema_version": "1.0.0",
  "task_id": "string",
  "result_type": "answer|artifact|action|handoff|blocked_explanation",
  "verification_plan": ["string"],
  "done_definition": "string",
  "retry_policy": {
    "max_repairs": 1,
    "stop_on_blocker": true
  },
  "visibility_contract": {
    "ack": true,
    "progress": true,
    "blocker": true,
    "done": true
  }
}
```

默认值（MUST）：
- `schema_version = "1.0.0"`
- `result_type = "answer"`
- `verification_plan = []`
- `retry_policy.max_repairs = 1`
- `retry_policy.stop_on_blocker = true`
- `visibility_contract.ack = true`
- `visibility_contract.progress = true`
- `visibility_contract.blocker = true`
- `visibility_contract.done = true`

约束（MUST）：
- `task_id` 必须（MUST）与 `TaskEnvelopeV1.task_id` 一致。
- `done_definition` 不得（MUST NOT）为空。
- `verification_plan` 可以（MAY）为空，但运行时仍必须（MUST）执行 `acceptance_criteria` 检查。

### TaskBundleV1（MUST）

- `TaskBundleV1` 必须（MUST）引用 `TaskEnvelopeV1.objective` 与 `DeliveryContractV1`，但不得（MUST NOT）重写两者的语义。
- `TaskBundleV1.completion_contract_ref` 必须（MUST）稳定指向当前 turn 的交付合同。
- `TaskBundleV1.worker_task_admission_mode` 默认必须（MUST）为 `leader_gate`。
- worker 若需要继续拆分，必须（MUST）提交 `split_request`，不得（MUST NOT）直接落子任务。
- `TaskBundleV1.file_refs` 中的 `workspace_path` 必须（MUST）遵守 `docs/specs/MVP_049_BUILTIN_FS_PATH_RESOLUTION.md`。
- 当 `TaskBundleV1.sufficient_for_execution=true` 时，worker 应该（SHOULD）优先依赖 bundle 自身信息，而不是回看父上下文。

### ProgressEventV1（MUST）

```json
{
  "schema_version": "1.0.0",
  "task_id": "string",
  "state": "ack|progress|blocker|hold|done",
  "summary": "string",
  "blocker_code": "string|null",
  "evidence_refs": ["string"]
}
```

默认值（MUST）：
- `schema_version = "1.0.0"`
- `blocker_code = null`
- `evidence_refs = []`

## 语义（Semantics）

### 输入编译（MUST）

- Submitter Adapter 必须（MUST）只负责接收外部请求、裁剪无关输入并提交到 Canonical Task Ingress。
- Submitter Adapter 不得（MUST NOT）内置独立的 prompt 拼装、done 判定或记忆写入逻辑。
- 运行时在任何执行模型或工具调用前，必须（MUST）先把原始输入编译为 `TaskEnvelopeV1`。
- 当输入只是简短闲聊、确认词或低风险单步请求时，运行时可以（MAY）编译为极小任务，但仍必须（MUST）保留 `objective` 与最小 `acceptance_criteria`。
- 当同一对话中出现目标切换时，运行时必须（MUST）决定：
  - 更新现有 `task_id`
  - 或开启新的 `task_id`
  - 并将该决定写入 trace/evidence。

### 最小上下文信封（MUST）

- 执行模型输入必须（MUST）基于 `TaskEnvelopeV1`、被选中的最小 evidence、当前公理/约束与下一步候选动作构成。
- 运行时不得（MUST NOT）默认把完整对话 transcript、长 JSON schema 或无关历史注入执行 prompt。
- 当需要详细结构或正文时，应该（SHOULD）通过引用方式交给运行时或工具，而不是全文展开进主 prompt。

### 检索优先（MUST）

- 当任务涉及历史偏好、既有工件、过去失败、已有 SOP/anti-pattern 或外部事实时，运行时必须（MUST）先执行检索，再决定是否写入新记忆。
- 若检索被策略禁止或资源缺失，运行时必须（MUST）显式记录该阻断，而不是静默跳过。
- 对程序性记忆（Procedural Memory）的写入必须（MUST）仅发生在：
  - 通过验收的稳定成功路径
  - 或终局失败且已完成失败归因的路径

### 验收驱动闭环（MUST）

- 执行完成后，运行时必须（MUST）依据 `DeliveryContractV1` 与 `TaskEnvelopeV1.acceptance_criteria` 进行验证。
- 若验证失败且 `retry_policy.max_repairs` 仍有余额，运行时必须（MUST）进入最小修复循环。
- 若验证失败且预算耗尽，或 `stop_on_blocker=true` 且出现不可解阻断，运行时必须（MUST）进入 `blocked_explanation` 或终止解释路径。
- 若验证失败的主因是预算耗尽，运行时不得（MUST NOT）直接终止；必须（MUST）进入 `hold/HITL_REQUIRED`。
- 任何 `done` 状态都必须（MUST）对应一次通过的验收结果或明确的 `blocked_explanation` 交付形态。

### 过程可见（MUST）

- 非平凡任务必须（MUST）先发出 `ack`，再发出零到多次 `progress`，最后以 `blocker` 或 `done` 结束。
- 当任务在首轮即可同步完成时，运行时可以（MAY）合并 `ack + done`，但仍必须（MUST）满足 `DeliveryContractV1.visibility_contract`。
- `done` 后不得（MUST NOT）再发送 `progress` 或 `blocker`。
- `blocker` 后若进入恢复执行，必须（MUST）先产出新的 `progress` 或新的 `ack` 轮次说明。
- `hold` 必须（MUST）保留当前 trace、任务摘要、部分结果与 evidence refs，直到 HITL 或新的 leader 决策到来。
- Consumer Adapter 必须（MUST）只消费运行时发出的生命周期事件；不得（MUST NOT）自行合成未被运行时验证的 `done`。

### 失败沉淀（SHOULD）

- 终局失败应该（SHOULD）生成 anti-pattern 或等价失败记录。
- 重复成功路径应该（SHOULD）生成 SOP candidate 或等价程序性记忆候选。
- 失败沉淀与成功沉淀必须（MUST）关联 `task_id`、触发条件与 evidence refs。

## 边界条件（Boundary Conditions）

- 当任务是单步、低风险、无需检索的直接回答时，运行时可以（MAY）省略中间 `progress`。
- 当 `acceptance_criteria` 无法直接从用户输入提取时，编译器必须（MUST）合成最小标准，例如“输出直接回应 objective 且不违背约束”。
- 当 `source_inputs` 存在冲突摘要时，运行时必须（MUST）将冲突写入 `open_questions` 或进入 `blocker`。
- 当检索结果为空时，运行时可以（MAY）继续执行，但必须（MUST）记录“已检索但未命中”。

## 错误码（Error Codes）

- `E_TASK_ENVELOPE_INVALID`
- `E_DELIVERY_CONTRACT_INVALID`
- `E_PROGRESS_EVENT_ORDER_INVALID`
- `E_TASK_RETRIEVAL_REQUIRED`
- `E_DELIVERY_VERIFICATION_FAILED`
- `E_TASK_BLOCKED_CLARIFICATION_REQUIRED`
- `E_HITL_REQUIRED`

## 兼容策略（Compatibility）

- 本规范为 additive change，不修改既有 `ExecuteRequest` 顶层字段。
- `TaskEnvelopeV1` 与 `DeliveryContractV1` 可以（MAY）作为 `StructuredQueryV1` 的子对象，或通过 `workspace_snapshot/policy_context/evidence` 引用承载。
- 现有 assistant loop、dialog state machine 与 memory 系统可在不破坏既有 CLI 稳定输出的前提下逐步接入本规范。
- 现有 submitter/consumer 外层实现可以（MAY）保留适配层差异，但不得（MUST NOT）复制 runtime 主链。

## 可观测性（Observability）

运行时必须（MUST）记录：
- `task_id`
- 编译后的 `objective` 与 `deliverable` 摘要
- 每次验收通过/失败结果
- `ack/progress/blocker/done` 的状态迁移
- 是否发生“检索先于写入”
- 生成的 SOP/anti-pattern 引用

## 测试与验收（Tests/Acceptance）

必须（MUST）满足：
1. Schema 校验：
   - `TaskEnvelopeV1.acceptance_criteria` 边界 `0/1/16/17`
   - `DeliveryContractV1.done_definition` 为空时拒绝
2. 生命周期校验：
   - `done -> progress`
   - `done -> blocker`
   - `blocker -> done`（无恢复说明）必须失败
3. 执行闭环校验：
   - 未编译 `TaskEnvelopeV1` 即执行必须失败
   - 验收失败且 repair budget>0 时必须重试
   - 验收失败且 repair budget=0 时必须终止并解释
4. 检索优先校验：
   - 任务声明依赖历史上下文时，写入前必须有检索记录或显式阻断记录
5. 回归命令：
   - `PYTHONPATH=src python3 -m unittest discover -s tests -v`
