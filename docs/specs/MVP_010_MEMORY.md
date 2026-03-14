# MVP-010 记忆系统 V2（Memory System V2）

## 目的（Purpose）

本规范定义记忆系统 V2（Memory System V2）的唯一公开契约。实现必须（MUST）以结构化记忆记录（Structured Memory Record）与连续性记忆（Continuity Memory）为中心，统一长期记忆、会话连续性、检索链路与可回放证据。

## 范围（Scope）

本规范定义：
- `policy_context["memory_context"]` 的唯一 schema
- `builtin://memory.write/search/delete/compact` 的 V2 输入输出契约
- 连续性记忆（Continuity Memory）与长期记忆（Long-Term Memory）的分层语义
- V2 落盘目录、默认值、错误码、边界条件、兼容策略与验收

本规范不定义：
- 向量数据库（Vector Database）或远程索引服务的选型
- `ExecuteRequest` 顶层字段扩张

## 不可破坏约束（Non-Negotiables）

1. Evidence/Trace/Artifact 必须（MUST）继续作为唯一真相源（Source of Truth）。
2. `memory_context` 必须（MUST）只存在于 `ExecuteRequest.policy_context["memory_context"]`。
3. 记忆系统 V2 必须（MUST）继续作为唯一公开契约；运行时可以（MAY）提供受限的迁移兼容桥（Migration Compatibility Bridge），把旧输入或旧 L1 条目归一化为 V2 语义，但不得（MUST NOT）把旧 schema 重新暴露为 canonical public contract。
4. 旧目录 `data/memory/` 与 `data/runtime_snapshots/` 必须（MUST）被视为废弃；V2 runtime 不得（MUST NOT）把它们当作 canonical truth。仅 `data/memory/l1/` 可以（MAY）作为过渡期 L1 索引被读取或写入，且其语义必须（MUST）与对应 V2 record/evidence 等价。
5. 跨工作区（Cross-Workspace）召回必须（MUST） fail-closed。
6. replay-mode 下不得（MUST NOT）产生新的记忆写入、连续性写入、Evidence 写入或 Trace 写入。

## 分层模型（Layering Model）

- `L0 Continuity Memory`：当前 `(workspace_id, conversation_id)` 的连续性头（continuity head），承载当前会话状态。
- `L1 Query`：当前轮的记忆查询计划（memory query plan），承载查询文本、意图、作用域与过滤条件。
- `L2 Hits`：当前轮真正进入推理的结构化命中（structured hits）。

语义映射：
- `profile / preference` 主要对应语义记忆（Semantic Memory）。
- `procedure` 主要对应程序性记忆（Procedural Memory）。
- `anti_pattern` 主要对应失败经验记忆（Failure Pattern Memory）。
- `delivery_summary / note / turn_archive` 主要对应交付与会话沉淀记忆（Delivery / Conversational Memory）。

## memory_context 契约（Memory Context Contract）

### 放置位置（Placement）

`memory_context` 必须（MUST）存在于 `ExecuteRequest.policy_context["memory_context"]`。

### Schema（v2.0.0）

```json
{
  "schema_version": "2.0.0",
  "l0_continuity": {
    "workspace_id": "string",
    "conversation_id": "string|null",
    "active_project_id": "string|null",
    "pending_contract": {},
    "expected_next_user_act": "string|null",
    "blocker": {},
    "last_delivery_state": "string|null",
    "last_delivery_summary": "string|null",
    "last_user_query": "string|null",
    "last_user_query_at_utc": "string|null"
  },
  "l1_query": {
    "query": "string",
    "intent": "identity|preference|continuity|procedure|delivery|generic",
    "scope": {
      "workspace_id": "string",
      "conversation_id": "string|null",
      "project_id": "string|null"
    },
    "kinds": ["profile|preference|procedure|anti_pattern|delivery_summary|note|turn_archive"],
    "limit": 5,
    "include_stale": false,
    "include_deleted": false
  },
  "l2_hits": [
    {
      "record_id": "string",
      "evidence_ref": "ev_...",
      "kind": "string",
      "summary": "string",
      "scope": {},
      "source": "string",
      "tags": ["string"],
      "score": 0,
      "freshness": "active|stale|deleted",
      "conflict_group": "string|null"
    }
  ],
  "conflicts": [
    {
      "memory_key": "string",
      "record_ids": ["string"],
      "resolution": "ask_user"
    }
  ],
  "retrieval_ref": "ev_..."
}
```

规则：
- `schema_version` 必须（MUST）固定为 `"2.0.0"`。
- 字段集合必须（MUST）严格限定为 `l0_continuity / l1_query / l2_hits / conflicts / retrieval_ref`。
- 不存在某层字段时必须（MUST）视为 schema invalid，而不是“空层”。
- `retrieval_ref` 必须（MUST）指向可回放的 routing evidence。

## 记忆记录（Memory Record）

### Record Schema（v2.0.0）

```json
{
  "schema_version": "2.0.0",
  "type": "memory_record_v2",
  "record_id": "string",
  "evidence_ref": "ev_...",
  "kind": "profile|preference|procedure|anti_pattern|delivery_summary|note|turn_archive",
  "summary": "string",
  "payload": {},
  "memory_key": "string",
  "scope": {
    "workspace_id": "string",
    "conversation_id": "string|null",
    "project_id": "string|null"
  },
  "source": "user_explicit|assistant_inferred|system_consolidated",
  "tags": ["string"],
  "ttl_seconds": 0,
  "created_at_utc": "UTC ISO",
  "updated_at_utc": "UTC ISO",
  "expires_at_utc": "UTC ISO|null",
  "deleted_at_utc": "UTC ISO|null",
  "superseded_by": "string|null"
}
```

规则：
- `summary` 必须（MUST）非空。
- `payload` 必须（MUST）为 JSON object。
- `memory_key` 必须（MUST）非空，用于冲突检测与 compact。
- `scope.workspace_id` 必须（MUST）与 `ExecuteRequest.workspace_id` 一致。
- `turn_archive` 仅在显式要求保留原文时可以（MAY）写入；普通成功回合不得（MUST NOT）默认写入 `turn_archive`。

kind 约束：
- `profile` 的 `payload` 必须（MUST）包含 `subject` 与 `value`。
- `preference` 的 `payload` 必须（MUST）包含 `subject` 与 `value`。
- `procedure` 的 `payload` 必须（MUST）包含 `objective`。
- `anti_pattern` 的 `payload` 必须（MUST）包含 `failure_mode`。
- `delivery_summary` 的 `payload` 必须（MUST）包含 `objective` 与 `result`。
- `note` 的 `payload` 必须（MUST）至少包含 `text` 或 `statement` 之一。
- `turn_archive` 的 `payload` 必须（MUST）包含 `user_text` 与 `assistant_text`。

## 特权技能（Privileged Skills）

### memory.write

输入：
```json
{
  "schema_version": "2.0.0",
  "record": {
    "kind": "string",
    "summary": "string",
    "payload": {},
    "memory_key": "string",
    "scope": {
      "workspace_id": "string",
      "conversation_id": "string|null",
      "project_id": "string|null"
    },
    "source": "user_explicit|assistant_inferred|system_consolidated",
    "tags": ["string"],
    "ttl_seconds": 0
  }
}
```

输出：
```json
{
  "schema_version": "2.0.0",
  "ok": true,
  "error_code": null,
  "record_id": "string",
  "evidence_ref": "ev_...",
  "scope": {
    "workspace_id": "string",
    "conversation_id": "string|null",
    "project_id": "string|null"
  },
  "evidence_refs": ["ev_..."]
}
```

规则：
- 写入前必须（MUST）完成脱敏。
- 写入后必须（MUST）同时生成 Evidence 与 `data/memory_v2/records/`、`data/memory_v2/index/` 记录。
- `ttl_seconds=0` 表示永久保存，直到 delete 或 compact。

### memory.write 兼容归一化（Compatibility Normalization）

输入：
```json
{
  "content": "string|null",
  "text": "string|null",
  "statement": "string|null",
  "tags": ["string"],
  "ttl_seconds": 0,
  "memory_key": "string|null",
  "source": "user_explicit|legacy_import|null"
}
```

规则：
- 兼容输入只可以（MAY）表达 `kind = "note"` 的 V2 语义。
- 当 `record` 与兼容字段同时存在时，运行时必须（MUST）优先采用 `record`。
- 运行时必须（MUST）先把兼容输入归一化成 V2 `record`，再执行 schema 校验、Evidence 写入与持久化。
- `payload.statement` 必须（MUST）取 `content / text / statement` 中第一个非空字符串。
- `summary` 应该（SHOULD）默认取 `payload.statement` 的前 160 个字符。
- `scope.workspace_id` 必须（MUST）默认绑定 `ExecuteRequest.workspace_id`。
- `source` 缺失时必须（MUST）默认成 `user_explicit`；`legacy_import` 可以（MAY）归一化成 `system_consolidated`。
- `memory_key` 缺失时必须（MUST）由 `workspace_id + content` 稳定派生，保证同输入 deterministic。
- 兼容输入的输出仍必须（MUST）保持本规范定义的 V2 输出形状。

### memory.write 语义适配（Semantic Adapter）

规则：
- 当 `record` 不是 canonical V2 record，但表达的是高层记忆意图时，运行时必须（MUST）先做语义适配，再进入 V2 `record` 校验。
- 语义适配输入可以（MAY）包含 `type`、legacy `kind`、`name`、`value`、`metadata.field`、`content/text/statement` 等字段；运行时不得（MUST NOT）把这些 legacy alias 直接透传给 V2 validator。
- 身份类输入必须（MUST）被归一化为：
  - `kind = "profile"`
  - `memory_key = "profile.identity.name"`
  - `payload.subject = "identity.name"`
  - `payload.value = <姓名>`
- 偏好类输入必须（MUST）被归一化为：
  - `kind = "preference"`
  - `payload.subject = "preference"`
  - `payload.value = <偏好值>`
- `type=user_profile`、`kind=user_profile`、`metadata.field in {"name","username"}` 等 identity alias 必须（MUST）视为身份类输入。
- `type=user_preference`、`kind=user_preference`、`metadata.field in {"preference","favorite","like"}` 等 preference alias 必须（MUST）视为偏好类输入。
- 语义适配后的 `source/tags/ttl_seconds` 应该（SHOULD）尽量保留调用方提供的信息；缺失时必须（MUST）回落到本规范默认值。
- 语义适配后仍无法形成 canonical V2 `record` 时，运行时必须（MUST）返回 `E_INPUT_SCHEMA`。

### memory.search

输入：
```json
{
  "schema_version": "2.0.0",
  "query": "string",
  "intent": "identity|preference|continuity|procedure|delivery|generic",
  "scope": {
    "workspace_id": "string",
    "conversation_id": "string|null",
    "project_id": "string|null"
  },
  "kinds": ["string"],
  "limit": 5,
  "include_stale": false,
  "include_deleted": false
}
```

输出：
```json
{
  "schema_version": "2.0.0",
  "ok": true,
  "error_code": null,
  "results": [
    {
      "record_id": "string",
      "evidence_ref": "ev_...",
      "kind": "string",
      "summary": "string",
      "scope": {},
      "source": "string",
      "tags": ["string"],
      "score": 0,
      "freshness": "active|stale|deleted",
      "conflict_group": "string|null"
    }
  ],
  "conflicts": [
    {
      "memory_key": "string",
      "record_ids": ["string"],
      "resolution": "ask_user"
    }
  ],
  "retrieval_trace_ref": "ev_...",
  "evidence_refs": ["ev_..."]
}
```

规则：
- 排序必须（MUST）遵循 `scope > kind whitelist > relevance > freshness > recency`。
- `include_stale=false` 时，stale 记录不得（MUST NOT）进入结果。
- `include_deleted=false` 时，deleted 记录不得（MUST NOT）进入结果。
- 命中冲突时必须（MUST）输出 `conflicts[]`。

### memory.delete

输入：
```json
{
  "schema_version": "2.0.0",
  "record_ids": ["string"]
}
```

输出：
```json
{
  "schema_version": "2.0.0",
  "ok": true,
  "error_code": null,
  "deleted_record_ids": ["string"],
  "evidence_refs": ["ev_..."]
}
```

规则：
- delete 必须（MUST）是逻辑遗忘（logical delete）。
- 被 delete 的记录默认检索必须（MUST）不可见。

### memory.compact

输入：
```json
{
  "schema_version": "2.0.0",
  "memory_key": "string",
  "scope": {
    "workspace_id": "string",
    "conversation_id": "string|null",
    "project_id": "string|null"
  },
  "winner": {
    "kind": "string",
    "summary": "string",
    "payload": {},
    "source": "system_consolidated",
    "tags": ["string"],
    "ttl_seconds": 0
  }
}
```

输出：
```json
{
  "schema_version": "2.0.0",
  "ok": true,
  "error_code": null,
  "winner_record_id": "string",
  "superseded_record_ids": ["string"],
  "evidence_refs": ["ev_..."]
}
```

规则：
- compact 必须（MUST）按 `memory_key + scope` 选择候选。
- compact 必须（MUST）生成新的 winner 记录。
- 被 compact 的源记录必须（MUST）写 `superseded_by`，不得物理删除。

## 默认值（Defaults）

- `memory.search.limit` 默认 `5`。
- `memory.search.include_stale` 默认 `false`。
- `memory.search.include_deleted` 默认 `false`。
- `Continuity Event` 保留窗口默认 `50` 条。
- `delivery_summary.ttl_seconds` 默认 `2592000`。
- `note.ttl_seconds` 默认 `2592000`。
- `turn_archive.ttl_seconds` 默认 `604800`。
- `profile / preference / procedure / anti_pattern.ttl_seconds` 默认 `0`。

## 错误码（Error Codes）

- `E_MEMORY_V2_SCHEMA_INVALID`
- `E_MEMORY_V2_SCOPE_INVALID`
- `E_MEMORY_V2_NOT_FOUND`
- `E_MEMORY_V2_CONFLICT`
- `E_MEMORY_V2_COMPACT_EMPTY`
- `E_MEMORY_V2_REPLAY_DENY`
- `E_MEMORY_V2_INTERNAL`

## 边界条件（Boundary Conditions）

- 同一 `memory_key` 下存在多个 active 且值冲突时，回答层必须（MUST）优先澄清。
- `scope.workspace_id` 缺失或不匹配时，必须（MUST）拒绝。
- 连续性头不存在时，系统必须（MUST）生成空 `l0_continuity`，而不是回退到旧 snapshot。
- `turn_archive` 不得（MUST NOT）参与默认 generic 查询，除非显式包含在 `kinds` 中。

## 兼容策略（Compatibility Strategy）

- `memory_context`、`memory_record_v2` 与 `builtin://memory.*` 的 V2 输入输出继续作为唯一公开契约。
- 运行时可以（MAY）保留受限迁移兼容桥，用于：
  - `builtin://memory.write` 的旧 flat note 输入归一化
  - `data/memory/l1/` 的旧 L1 索引条目兼容读取或镜像写入
- 新写入必须（MUST）继续落到 `data/memory_v2/records/` 与 `data/memory_v2/index/`。
- 迁移兼容桥不得（MUST NOT）绕过 workspace 隔离、replay-mode 零写、脱敏、Evidence 或 V2 schema 校验。
- `data/runtime_snapshots/` 仍然禁止（MUST NOT）作为记忆系统 V2 的读取来源。

## 测试与验收（Tests and Acceptance）

必须（MUST）覆盖：
1. `memory.write/search/delete/compact` 的 V2 结构化契约
2. `scope` 隔离与 cross-workspace fail-closed
3. `scope > kind > relevance > freshness > recency` 排序
4. `active > stale > deleted`
5. `memory_key` 冲突检测
6. continuity head 与 continuity events 的读写与回放
7. `memory_context` 仅包含 `l0_continuity / l1_query / l2_hits / conflicts / retrieval_ref`
8. `memory.write` 兼容 flat note 输入的归一化与 deterministic `memory_key` 派生
9. 旧 `data/memory/l1/` 条目与 V2 records 必须（MUST）都能被 Context Compiler 读取，且不得产生 cross-workspace leakage

验收命令必须（MUST）包含：
- `PYTHONPATH=src python3 -m unittest tests/test_memory_v2_store.py -v`
- `PYTHONPATH=src python3 -m unittest tests/test_spike_memapi1_builtin_memory.py -v`
- `PYTHONPATH=src python3 -m unittest tests/test_thread043_pa_mem1_pipeline.py -v`
- `PYTHONPATH=src python3 -m unittest tests/test_thread044_pa_polling.py tests/test_thread041_pa_webhook_server.py -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread030_capability_schema tests.test_eval_memory_effect tests.test_thread032_context_compiler -v`
