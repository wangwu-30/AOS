# MVP-043 PA 记忆上下文管线 V2（PA Memory Context Pipeline V2）

## 1. 目标（Purpose）

个人助理记忆上下文管线（Personal Assistant Memory Context Pipeline）必须（MUST）为 assistant-loop、polling、webhook、EV1 提供同一套记忆上下文装配器（Memory Assembler），并且只输出 `policy_context["memory_context"]` 的 V2 canonical 结构。

## 2. 默认值（Defaults）

- `memory_context_enabled` 默认 `false`（MUST）。
- `memory_context_retrieval_limit` 默认 `8`（MUST）。
- `memory_context_include_stale` 默认 `false`（MUST）。
- `memory_context_audit_mode` 默认 `false`（MUST）。
- `memory_context_continuity_event_limit` 默认 `50`（MUST）。

## 3. 输入（Inputs）

启用管线时，输入必须（MUST）包含：
- `workspace_id`
- `conversation_id`
- `query`

运行时可以（MAY）附带：
- `project_id`
- `retrieval_limit`
- `include_stale`
- `audit_mode`

禁止项：
- 不得（MUST NOT）再要求 `meta_identity_ref`
- 不得（MUST NOT）再要求 `meta_operator_catalog_ref`
- 不得（MUST NOT）再使用 inline fallback
- 不得（MUST NOT）再通过自定义 prompt 拼接 memory 片段

## 4. 输出（Outputs）

输出必须（MUST）是：

```json
{
  "schema_version": "2.0.0",
  "l0_continuity": {},
  "l1_query": {},
  "l2_hits": [],
  "conflicts": [],
  "retrieval_ref": "ev_..."
}
```

其中：
- `l0_continuity` 必须（MUST）来自 continuity head，而不是旧 `runtime_snapshot` 目录
- `l1_query` 必须（MUST）记录 query、intent、scope、kinds、limit、include_stale、include_deleted
- `l2_hits` 必须（MUST）只包含当前轮实际选中的结果
- `conflicts` 必须（MUST）显式表达冲突组
- `retrieval_ref` 必须（MUST）指向 routing evidence

## 5. 规则（Rules）

- 管线必须（MUST）统一使用同一个 `Memory Assembler` 实现。
- assistant-loop、polling、webhook、EV1 必须（MUST）调用同一条装配逻辑。
- 管线必须（MUST）先读取 continuity head，再执行长期记忆检索。
- 检索排序必须（MUST）遵循 `scope > kind whitelist > relevance > freshness > recency`。
- `memory_context_enabled=false` 时，不得（MUST NOT）注入 `memory_context`。
- `memory_context_enabled=true` 且装配失败时，入口必须（MUST） fail-closed。
- 管线输出不得（MUST NOT）包含 `meta_context / l0_session_inline / l1_short_refs / l2_long_query / capsules / selection_trace`。

## 6. 错误码（Error Codes）

- `E_PA_MEM_CONTEXT_FAILED`
- `E_PA_MEM_SCHEMA_INVALID`
- `E_PA_MEM_SCOPE_INVALID`
- `E_PA_MEM_REPLAY_DENY`

## 7. 边界条件（Boundary Conditions）

- continuity head 不存在时，必须（MUST）生成空 `l0_continuity`，字段形状仍须有效。
- `conversation_id` 缺失时，必须（MUST）只允许 workspace 级查询，不得伪造 conversation 级 continuity。
- `limit <= 0` 时，必须（MUST）视为 schema invalid。
- `audit_mode=true` 时才可以（MAY）在 replay 语义下开启 `include_deleted=true`；普通用户流不得（MUST NOT）默认开启。
- replay-mode 下不得（MUST NOT）写 continuity head、continuity events、retrieval evidence 或记忆记录。

## 8. 兼容策略（Compatibility Strategy）

- 本规范不存在（MUST NOT） alias、legacy 字段或 fallback 路径。
- 旧 `PA-MEM1` 输出形状必须（MUST）整体废弃。
- 旧 `data/memory/` 与 `data/runtime_snapshots/` 必须（MUST）从 PA 入口读取路径中移除。

## 9. 测试与验收（Tests and Acceptance）

必须（MUST）覆盖：
1. assistant-loop / polling / webhook / EV1 四条入口的统一注入
2. `memory_context_enabled=true` 时的成功装配
3. 装配失败时 fail-closed
4. continuity head 缺失时的空 `l0_continuity`
5. 命中冲突时 `conflicts[]` 输出
6. replay-mode 零写

验收命令（MUST）：
- `PYTHONPATH=src python3 -m unittest tests/test_thread043_pa_mem1_pipeline.py -v`
- `PYTHONPATH=src python3 -m unittest tests/test_memory_v2_store.py tests/test_spike_memapi1_builtin_memory.py -v`
- `PYTHONPATH=src python3 -m unittest tests/test_thread044_pa_polling.py tests/test_thread041_pa_webhook_server.py -v`
