# MVP_011_ASSISTANT_LOOP

- 状态（Status）：Draft
- 日期（Date）：2026-03-12
- 目标版本（Target）：MVP_011
- 相关规范（Related Specs）：
  - `docs/specs/MVP_030_CAPABILITY_SCHEMA.md`
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_047_WEB_SEARCH_ROUTING.md`
  - `docs/specs/MVP_054_EXPLICIT_RESEARCH_RUN.md`

## 目的（Purpose）

定义助理循环（Assistant Loop）的最小 canonical 执行闭环，使模型在受限 operator surface 内完成多步推理、动作执行、验证与显式消息交付。

## 阶段（Phases）

一次 Assistant Loop 必须（MUST）按以下阶段执行：
1. `intent_router`
2. `planner`
3. `executor`
4. `verifier_replanner`
5. `communicator`
6. `builtin://channel.send_message`

## ActionGraphV1（MUST）

最小 action 字段：
- `action_id`
- `operator_ref`
- `arguments`
- `depends_on`

规则（MUST）：
- `depends_on` 只能（MUST）引用精确 `action_id`。
- 上游结果引用只能（MUST）使用结构化对象：

```json
{
  "$from_action": "lookup_web",
  "path": ["results", 0, "url"]
}
```

- 运行时不得（MUST NOT）再支持：
  - `a1/a2/...` 位置别名
  - `{{...}}`
  - `${...}`
  - `skill_ref/input`
  - `dependsOn`
  - `task_id|id` 作为 action 标识

## Delivery（MUST）

- 只有 `communicator` 可以（MAY）产出用户可见自然语言。
- 最终交付必须（MUST）通过 `builtin://channel.send_message` 完成。
- 非 `communicator` phase 不得（MUST NOT）直接交付消息。
- `builtin://telegram.*` 不再属于 canonical assistant loop surface。

## 能力输入（Capabilities）

- Assistant Loop 必须（MUST）只读取 `EffectiveRuntimeCapabilitiesV1`。
- step policy 中的额外能力（例如 `channel_send`、`scheduler_write`）必须（MUST）通过该对象派生，不得各自另建一套判断。

## Web / Research Operators（MUST）

- Assistant Loop 在 worker execution seam 只能（MUST）消费 canonical operator surface：
  - `builtin://web.search(query, limit?)`
  - `builtin://web.browse(url)`
  - `builtin://research.run(objective, depth?, report_format?, min_sources?)`
- Assistant Loop 不得（MUST NOT）暴露或依赖主题专名 operator，例如 `search_weather`。
- 当任务为普通外部信息查询且启用自动 browse bridge 时，运行时必须（MUST）按 `external_evidence_policy_v1` 在候选 URL 列表内有界尝试；不得（MUST NOT）假定“最近一次 search 的第一个结果”总是唯一 browse 目标。
- 当任务未被 Query Compile 标记为显式调研（Explicit Research）时，Assistant Loop 不得（MUST NOT）向模型暴露 `builtin://research.run`。

## 默认值（Defaults）

- `loops_max = 2`
- `tool_calls_max = 6`
- `time_ms_max = null`

## 错误码（Error Codes）

- `E_ACTION_OPERATOR_UNSUPPORTED`
- `E_TASK_DEPENDENCY_UNRESOLVED`
- `E_TASK_DEPENDENCY_CYCLE`
- `E_TASK_ARGUMENT_REFERENCE_INVALID`
- `E_MESSAGE_TASK_MISSING`
- `E_MESSAGE_TASK_PHASE_VIOLATION`
- `E_EXECUTION_FAILED`
- `E_TIMEOUT`

## 边界条件（Boundary Conditions）

- 非 `builtin://` action 不得（MUST NOT）在 canonical path 直接执行。
- 当依赖未满足时，action 必须（MUST）稳定跳过或失败，不得静默改写依赖。
- communicator 若未产出最终消息，运行时必须（MUST）返回 `E_MESSAGE_TASK_MISSING`。

## 兼容策略（Compatibility）

- 新输出 schema 必须（MUST）使用 `action_id`；不得再写 `task_id` 作为 action 标识。
- 历史 alias/template 语义不再保证兼容。

## 测试与验收（Tests/Acceptance）

必须（MUST）满足：
1. strict `action_id + depends_on` DAG 可以执行。
2. `$from_action` 结构化引用可以解析。
3. `a1`/模板字符串必须被拒绝。
4. communicator 只能暴露 `builtin://channel.send_message`。
5. Assistant Loop 不得暴露 `search_weather` 一类主题专名 operator。
6. 对普通外部证据任务，自动 browse bridge 必须按候选预算而不是单一首结果工作。

验收命令（MUST）：
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime -v`
