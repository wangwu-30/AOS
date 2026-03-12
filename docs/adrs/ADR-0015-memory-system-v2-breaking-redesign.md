# ADR-0015 记忆系统 V2 破坏式重设计（Memory System V2 Breaking Redesign）

- 状态（Status）：Accepted
- 日期（Date）：2026-03-11
- 相关规范（Related Specs）：
  - `docs/specs/MVP_010_MEMORY.md`
  - `docs/specs/MVP_043_PA_MEM1_CONTEXT_PIPELINE.md`

## 背景（Context）

既有记忆实现将长期记忆、`runtime_snapshot`、上下文编译、inline fallback 与渠道入口拆成多套逻辑。该结构导致同一用户状态可能在不同入口被不同规则消费，并且旧 `memory_context` schema 含有多组 alias 与旁路字段，增加了理解成本与验证成本。

## 决策（Decision）

1. 采用记忆系统 V2（Memory System V2）作为唯一实现方向。
2. 将 `runtime_snapshot` 并入连续性记忆（Continuity Memory），作为 `L0`。
3. 保持 `memory_context` 继续承载于 `policy_context["memory_context"]`，但 schema 直接升级为 `2.0.0`。
4. 删除 legacy alias、legacy schema、legacy inline fallback 与 runtime 兼容分支。
5. 旧目录 `data/memory/` 与 `data/runtime_snapshots/` 直接废弃，V2 runtime 不再读取。
6. `builtin://memory.write/search/delete/compact` 全部升级为 V2 结构化契约。

## 备选方案（Alternatives）

### 方案 A：保留 legacy alias 并渐进迁移

不采用。原因：会继续保留双重语义与双重测试负担。

### 方案 B：把 `memory_context` 升格到 `ExecuteRequest` 顶层字段

不采用。原因：当前问题核心在记忆域模型与装配链路，而非 carrier 位置。

### 方案 C：只重做长期记忆，不动 `runtime_snapshot`

不采用。原因：会继续保留连续性记忆与长期记忆分裂的问题。

## 取舍（Tradeoffs）

- 优点：
  - 实现边界更清晰
  - 测试口径更单一
  - 检索与连续性可被同一套规则治理
- 代价：
  - 直接 breaking change
  - 旧数据失效
  - 旧测试与旧文档必须同步重写

## 后果（Consequences）

- 渠道入口必须（MUST）统一依赖同一 `Memory Assembler`。
- `memory_context` 必须（MUST）只包含 `l0_continuity / l1_query / l2_hits / conflicts / retrieval_ref`。
- assistant-loop、polling、webhook、EV1 的记忆注入路径将被强制收敛。
- 任何依赖旧 `l0_session_inline / l1_short_refs / capsules / l2_long_query` 的实现必须（MUST）被移除。

## 风险与缓解（Risks & Mitigations）

- 风险：破坏式重构造成短期回归。
  - 缓解：以统一的 V2 验收集覆盖 builtin memory、PA 注入、continuity 与 eval。
- 风险：旧数据不可读导致现场状态丢失。
  - 缓解：明确声明旧数据废弃，不在 runtime 维持任何隐式迁移。
- 风险：入口实现重新分叉。
  - 缓解：将装配逻辑集中到单一组件，并以入口级测试锁定。

## 可观测与验收（Metrics & Acceptance）

- 每次 `memory.search` 必须（MUST）产出 `retrieval_trace_ref`。
- 每次 `memory_context` 装配必须（MUST）产出 `retrieval_ref`。
- continuity head 与 continuity events 必须（MUST）可从落盘目录审计。
- 验收必须（MUST）至少包含：
  - `tests/test_memory_v2_store.py`
  - `tests/test_spike_memapi1_builtin_memory.py`
  - `tests/test_thread043_pa_mem1_pipeline.py`
  - `tests/test_thread044_pa_polling.py`
  - `tests/test_thread041_pa_webhook_server.py`

## 后续工作（Follow-ups）

1. 用统一 V2 测试替换所有 legacy memory tests。
2. 更新评测数据集，覆盖冲突、continuity、逻辑遗忘与 procedure/anti-pattern。
3. 清理代码中所有 legacy memory 字段与旧目录引用。
