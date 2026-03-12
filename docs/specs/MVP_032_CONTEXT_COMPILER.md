# MVP_032 上下文编译器（Context Compiler）

## 1. 目的（Purpose）

THREAD-032 必须（MUST）定义运行时如何把元信息（Meta Context）、运行时快照（L0 Snapshot）、索引层（L1 Index）与实际检索结果（L2 Retrieved Evidence Pack）编译成单步可消费上下文。

本规范的核心目标不是“拼更多文本”，而是：

- 渐进式披露（Progressive Disclosure）
- 单事实单归属（Single Fact Ownership）
- 预算内裁剪（Budgeted Selection）
- 可审计检索（Auditable Retrieval）

## 2. 规范对象（Canonical Layers）

### 2.1 Meta Context（MUST）

Meta Context 必须（MUST）包含与当前回合相关、但不属于记忆本体的稳定元信息：

- `Meta.Identity`：身份/灵魂/沟通边界种子
- `Meta.OperatorCatalog`：操作符目录种子（operator catalog seed），用于渐进式披露

Meta Context 必须（MUST）被视为编译输入，而不是记忆层。

### 2.2 L0 Snapshot（MUST）

L0 Snapshot 必须（MUST）表示当前回合可物化的运行时快照，例如：

- budget remaining
- approvals pending
- last error code
- task state digest

L0 Snapshot 应该（SHOULD）来自事件流归约，而不是直接来自自由文本 transcript。

### 2.3 L1 Index（MUST）

L1 Index 必须（MUST）表示用于检索导航的索引/手册层，而不是最终事实正文，包括：

- tag index
- workspace/project scope anchors
- directory / artifact / memory catalog
- operator / skill seed refs

### 2.4 L2 Retrieved Evidence Pack（MUST）

L2 Retrieved Evidence Pack 必须（MUST）表示本轮被真正选中的检索结果。  
L2 应该（SHOULD）以 `ref + preview` 或等价短摘要形态进入执行上下文，不得默认拼接全文档或全文聊天历史。

### 2.5 Step Context（MUST）

Step Context 是面向单步推理的编译结果。  
Step Context 可以（MAY）包含 `Meta + L0 + L2 + TaskIntent` 的投影，但不得（MUST NOT）把它们重新混写为不可区分的长段 transcript。

## 3. 兼容映射（Compatibility Mapping）

为兼容既有实现，本规范允许（MAY）保留以下 legacy alias，但文档口径必须（MUST）以 canonical vocabulary 为准：

- `C0` -> `Meta.Identity`
- `C1` -> `Meta.OperatorCatalog`
- `C2` -> `L1/L2 retrieval path`
- `C3` -> `L0 Snapshot`
- `C4` -> `Step Context`

实现若继续输出 `c0/c1/c2_*/c3/c4` 命名，只能（MAY）作为兼容别名；新增实现应该（SHOULD）同时输出 canonical alias。

## 4. 默认值（Defaults）

- `MemoryQuery.limit` 默认 `5`（MUST）。
- `MemoryQuery.include_stale_fallback` 默认 `true`（MUST）。
- `MemoryQuery.include_tombstoned_fallback` 默认 `false`（MUST）。
- `MemoryQuery.freshness_window_seconds` 默认 `null`（MAY），表示仅执行 TTL/软删除过滤，不额外执行 freshness window。
- `ContextBudgets.max_bytes_total` 必须（MUST）大于 `0`。

## 5. 预算与裁剪（Budgeting and Trimming）

- Meta Context 必须（MUST）视为 pinned，不得裁剪。
- 当总上下文超出预算时，必须（MUST）优先裁剪：
  1. L2 正文细节
  2. L1 索引投影
  3. fail-closed
- 若预算不足以容纳 Meta Context + L0 Snapshot + TaskIntent，则必须（MUST）返回 `E_CTX_BUDGET_EXCEEDED`。
- 运行时应该（SHOULD）维持 `40%~70%` 的 Goldilocks usage ratio。

## 6. 检索顺序（Retrieval Ordering）

- 当 `MemoryQuery.query` 存在时，L2 召回应该（SHOULD）优先按相关性排序。
- 当无相关性命中时，必须（MUST）回退到时间新近性排序。
- `MemoryQuery.tags` 必须（MUST）按“查询 tag 是记录 tag 的子集”匹配；不得使用 OR 扩召。
- L2 召回必须（MUST）按以下顺序执行：
  1. 强时效且未软删除
  2. 弱时效且未软删除
  3. 软删除 fallback
- 第二层与第三层不得（MUST NOT）默认参与；只有当上一级 context 不足时才可以（MAY）激活。
- 软删除 fallback 被激活时，结果必须（MUST）显式标弱证据。

## 7. 错误码（Error Codes）

- `E_CTX_SCHEMA_INVALID`
- `E_CTX_BUDGET_EXCEEDED`
- `E_CTX_POLICY_VIOLATION`
- `E_CTX_REPLAY_DENY`

## 8. 边界条件（Boundary Conditions）

- replay mode 下若 `evidence/` 或 `memory/` 缺失，必须（MUST）返回 `E_CTX_REPLAY_DENY`。
- 跨 workspace 泄漏必须（MUST）fail-closed，返回 `E_CTX_POLICY_VIOLATION`。
- 请求显式变更 identity 时，必须（MUST）拒绝并记录 `identity_mutation_attempt`。
- 请求 squash/prune history 时，可以（MAY）继续执行，但必须（MUST）记录 `append_only_violation`。

## 9. 可观测与审计（Observability and Audit）

Context Compiler 必须（MUST）输出 `selection_trace`，至少包含：

- decision log
- violations
- selected refs
- stale fallback 是否触发
- tombstoned fallback 是否触发

非 replay mode 下，`selection_trace` 必须（MUST）写入 `kind=context_routing` 的 Evidence。

## 10. 测试与验收（Tests and Acceptance）

必须（MUST）覆盖：

1. 同输入 deterministic
2. replay mode zero-write
3. cross-workspace leakage fail-closed
4. Meta Context pinned
5. budget trim order 稳定
6. relevance ranking 优先于 recency
7. stale / tombstoned fallback 顺序正确
8. canonical alias 与 legacy alias 可同时存在

验收命令（MUST）：

- `PYTHONPATH=src python3 -m unittest tests/test_thread032_context_compiler.py -v`
