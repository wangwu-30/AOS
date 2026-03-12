# ADR-0017：Runtime Graph Durable Scheduler 抽离

- 状态（Status）：Accepted
- 日期（Date）：2026-03-12
- 相关规范（Related Specs）：
  - `docs/specs/MVP_042_PA_TASK_GRAPH.md`
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_052_RUNTIME_GRAPH_WORKER_BUNDLE.md`
  - `docs/specs/MVP_053_RUNTIME_GRAPH_DURABLE_SCHEDULER.md`
  - `docs/specs/EVIDENCE_TRACE.md`

## 背景（Context）

`assistant_loop` 已经承担 Query-Gated Runtime 的 canonical 主链，但 `RuntimeGraph` 的 root bootstrap、step state 迁移、plan revision 推进与 action task 落盘此前都内嵌在同一个大函数里，带来三个问题：

- durable 写路径分散，难以保证单一真相源（single source of truth）
- action task 去重、result capsule 引用与后续恢复逻辑难以复用
- `assistant_runtime` / 后续 hybrid shell 若要复用 `RuntimeGraph`，必须再次复制调度细节

ADR-0016 当时选择“先不迁移 durable scheduler”是为了避免阻塞 bundle / hold 语义落地；现在这些语义已经冻结，继续把调度逻辑留在 loop 内部会成为后续演进阻力。

## 决策（Decision）

采用以下设计：

1. 新增运行时图耐久调度器（Runtime Graph Durable Scheduler），作为 `assistant_loop` 对 `runtime_graph_v1` 的唯一写边界。
2. 调度器必须（MUST）基于既有 `FileTaskGraphStore` 持久化，不新引入第二份状态存储。
3. 调度器必须（MUST）负责：
   - root bootstrap
   - compile failure 落盘
   - step result + leader decision 记录
   - action task 去重创建
   - replan revision 推进
   - root finalization
4. `assistant_loop` 保留业务阶段推进与验证逻辑，但不得（MUST NOT）再直接拼接 `TaskGraph` 持久化细节。
5. 调度器必须（MUST）保持既有 `RuntimeGraph` record id、root state 映射与 JSON 形状兼容。

## 备选方案（Alternatives Considered）

### 方案 A：继续把调度逻辑内嵌在 assistant_loop

未采纳。原因：

- 无法形成单一 durable 边界
- 后续 hybrid/runtime shell 复用成本高
- action task 恢复与去重逻辑会继续散落

### 方案 B：直接重写为全新的 daemon / queue runtime

未采纳。原因：

- 变更面过大
- 会把当前用户任务从“边界抽离”升级成“重写执行主链”
- 现有 TaskGraph / RuntimeGraph 合同已经足够承载最小 durable scheduler

### 方案 C：改用 scheduler_tick 或外部时间调度器承接 RuntimeGraph

未采纳。原因：

- 时间调度器解决的是“何时触发”，不是“如何维护单轮 RuntimeGraph 状态机”
- 会混淆外部时间触发与内部 execution scheduling 的职责

## 取舍（Trade-offs）

收益：

- `assistant_loop` 只负责业务阶段推进，`RuntimeGraph` 写路径变成可复用模块
- action task 去重与 result capsule 索引可在 graph reopen 时恢复
- 为 `assistant_runtime` / hybrid shell 后续接管 durable orchestration 提前冻结模块边界

代价：

- 引入一个新的调度器抽象层
- 当前仍是单写文件快照，不解决多写一致性
- 每次状态迁移的 durable save 更显式，调用点需要受控

## 后果（Consequences）

- `assistant_loop` 相关 `RuntimeGraph` 持久化调用改为依赖 durable scheduler。
- `runtime_graph_v1` 继续作为可审计真相源，不新增第二份 graph schema。
- 新增独立 spec `MVP_053_RUNTIME_GRAPH_DURABLE_SCHEDULER.md` 约束该边界。
- ADR-0016 中“暂不迁移 durable scheduler”的约束被部分替代，但 bundle / hold / leader-worker 边界结论继续有效。

## 风险与缓解（Risks and Mitigations）

- 风险：调度器抽象层与既有 RuntimeGraph 语义漂移。
  - 缓解：冻结 record id、root state 映射与 JSON 形状；通过 query_gated_runtime 回归测试锁定。
- 风险：graph reopen 后 action task 去重失效。
  - 缓解：调度器启动时重建 action task index 与 action result index。
- 风险：后续调用者绕过调度器再次直接写 `TaskGraph`。
  - 缓解：在 spec 中明确 assistant_loop 写路径必须经由 durable scheduler，并把新测试加入验收集。

## 可观测 / 验收（Observability / Acceptance）

必须可观测：

- root bootstrap
- compile failure
- step result capsule
- leader decision
- action task 去重后的稳定 task id
- replan revision 与 root finalization

验收命令：

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread053_runtime_graph_scheduler -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_persists_runtime_graph_records -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime.TestThread045QueryGatedRuntime.test_assistant_loop_continues_until_deadline_without_replan_budget_cutoff -v`
