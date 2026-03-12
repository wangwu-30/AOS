# ADR-0021 记忆系统 V2 迁移兼容桥（Memory System V2 Migration Compatibility Bridge）

- 状态（Status）：Accepted
- 日期（Date）：2026-03-13
- 相关规范（Related Specs）：
  - `docs/specs/MVP_010_MEMORY.md`
  - `docs/specs/MVP_032_CONTEXT_COMPILER.md`
  - `docs/specs/MVP_043_PA_MEM1_CONTEXT_PIPELINE.md`

## 背景（Context）

ADR-0015 将记忆系统 V2 定义为破坏式重设计，并要求删除所有 legacy runtime 兼容分支。该决策明确了长期方向，但在实际迁移中暴露出两个剩余约束：

1. 既有 Context Compiler 与 replay 场景仍消费 `data/memory/l1/` 的旧 L1 索引条目。
2. 既有 builtin 调用与评测仍会发送未包裹 `record` 的 flat `memory.write` note 输入。

若继续坚持“零兼容分支”，则需要在同一窗口内同步重写多条入口、旧测试、历史数据与回放样本，迁移风险过高，且会阻断对 V2 主链的验证。

## 决策（Decision）

1. 记忆系统 V2 继续作为唯一公开契约。
2. 运行时可以（MAY）保留一个受限迁移兼容桥，仅用于：
   - 将旧 flat `memory.write` note 输入归一化成 V2 `record`
   - 读取或镜像写入 `data/memory/l1/` 的旧 L1 索引条目
3. 所有对外可观察输出、Evidence、检索结果与 `memory_context` 必须（MUST）继续使用 V2 语义；兼容桥不得（MUST NOT）重新暴露旧 schema。
4. 迁移兼容桥不得（MUST NOT）绕过 workspace 隔离、replay-mode 零写、脱敏、Evidence 记录与 V2 schema 校验。
5. `data/runtime_snapshots/` 仍然禁止（MUST NOT）作为记忆系统 V2 的读取来源。

本 ADR 以受限迁移兼容桥的形式，收窄 ADR-0015 中“完全不保留 runtime 兼容分支”的执行口径，但不改变“V2 是唯一公开契约”的总方向。

## 备选方案（Alternatives）

### 方案 A：坚持零兼容分支并立即重写所有旧入口

不采用。原因：迁移窗口过长，且会同时放大 Context Compiler、eval、assistant loop 与历史 replay 样本的回归风险。

### 方案 B：把 V2 与旧 schema 同时提升为公开契约

不采用。原因：会重新引入双重公开语义，抵消 ADR-0015 带来的收敛收益。

### 方案 C：提供一次性离线迁移器，运行时完全不兼容

暂不采用。原因：历史测试样本、临时数据目录与开发态 builtin 输入并不总能在运行前先完成统一迁移。

## 取舍（Tradeoffs）

- 优点：
  - 保持 V2 公开契约不变
  - 降低 Context Compiler、eval 与 replay 样本的迁移断层
  - 允许逐步清理旧入口，而不阻断主链验证
- 代价：
  - 运行时需要维护一层窄口兼容归一化逻辑
  - `data/memory/l1/` 在过渡期内仍需被审计

## 后果（Consequences）

- `builtin://memory.write` 可以（MAY）接受旧 flat note 输入，但必须（MUST）先归一化为 V2 `record`。
- Context Compiler 可以（MAY）读取旧 L1 条目，但输出上下文不得（MUST NOT）暴露旧字段。
- 新写入仍必须（MUST）落入 `data/memory_v2/records/` 与 `data/memory_v2/index/`。
- 后续清理兼容桥时，必须（MUST）先确保旧入口、旧测试与 replay 样本已经全部迁移到 V2。

## 风险与缓解（Risks & Mitigations）

- 风险：兼容桥长期滞留，逐渐演化成第二套公开契约。
  - 缓解：Spec 明确其仅限归一化与过渡索引；所有输出仍锁定 V2。
- 风险：旧 L1 索引与 V2 records 语义漂移。
  - 缓解：要求兼容条目必须与对应 V2 record/evidence 等价，并由 Context Compiler/评测覆盖。
- 风险：兼容桥绕过 replay 零写与 workspace 隔离。
  - 缓解：保持 replay-mode 与 scope 校验不降级，并在验收中覆盖。

## 可观测与验收（Metrics & Acceptance）

- `memory.write` 的兼容输入必须（MUST）产出 V2 `tool_io` 与 V2 Evidence。
- Context Compiler 必须（MUST）同时验证旧 L1 条目与 V2 records 的读取一致性。
- 验收必须（MUST）至少包含：
  - `tests/test_thread030_capability_schema.py`
  - `tests/test_eval_memory_effect.py`
  - `tests/test_thread032_context_compiler.py`
  - `tests/test_thread043_pa_mem1_pipeline.py`

## 后续工作（Follow-ups）

1. 盘点所有仍依赖 flat `memory.write` 或 `data/memory/l1/` 的入口与评测。
2. 在旧样本全部迁移后，删除迁移兼容桥并回收 `data/memory/l1/`。
