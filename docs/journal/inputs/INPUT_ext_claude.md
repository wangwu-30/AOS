id: `20260214-ext_claude-001`
author: `ext_claude`
topic: `Round 1 架构对齐：语义北极星、过渡架构与不可破坏约束`
position:
- 对议题1（语义北极星）：**强烈支持**以 `Executor API (ExecuteRequest/ExecuteResult)` 作为唯一长期语义源。`docs/specs/EXECUTOR_API.md` 的设计已经体现了"执行器作为策略执行点(PEP)"的核心思想，这与我在之前的架构讨论中提出的"AgentOS = Skill Runtime"理念一致——Executor API 是 Runtime 的核心抽象层。
- 对议题2（过渡架构）：**有条件支持** `LocalExecutor.execute -> PackageRunner` 作为当前最小风险落点，但认为需要明确定义"落点"的含义——是代码复用还是语义映射？当前 `src/agentos_next/runtime/package_runner.py` 和 `src/agentos_next/kernel/executor.py` 是两条独立路径，PackageRunner 并没有调用 LocalExecutor。
- 对议题3（不可破坏约束）：**完全支持** fail-closed 与 admission 门禁不降级；但对"CLI JSON 字段稳定性"与"evidence/trace schema 稳定性"有条件保留——需要明确"稳定"的版本粒度（major/minor/patch）和变更流程。
- 核心差异点1：对 Executor API 的"唯一语义源"地位，需要明确定义"短期"与"长期"的边界——MVP 阶段的 PackageRunner 是否需要立即向 Executor API 收敛？还是允许并存直到下一个大版本？
- 核心差异点2：`execute_mapping.py` 当前的实现是 PackageRunResult -> ExecuteResult 的单向映射，这解决了"审计落点"问题，但**没有解决"执行入口统一"问题**。如果长期存在两套执行路径，语义漂移的风险仍然存在。
evidence:
- `docs/specs/EXECUTOR_API.md`: ExecuteRequest/ExecuteResult 的规范来源，已明确定义幂等、取消、超时、trace correlation 等核心语义。
- `src/agentos_next/kernel/executor.py`: 当前 Executor 接口实现，定义了抽象基类。
- `src/agentos_next/runtime/package_runner.py`: 当前 MVP 执行主路径，已稳定产出 evidence/trace。
- `src/agentos_next/runtime/execute_mapping.py`: Spike-B 已完成的映射层（PackageRunResult -> ExecuteResult）。
- `docs/specs/ADMISSION_TESTS.md`: 当前 admission 测试范围定义。
- `src/agentos_next/cli.py`: CLI 入口，定义 run-skill/run-package/assistant-demo 三个命令及其 JSON 输出字段。
- `docs/specs/VERSIONING_COMPAT.md`: 版本兼容性规范（待补充具体策略）。
- 命令结果：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`（验证当前测试状态）。
tradeoffs:
- 语义北极星（Executor API 唯一语义源）：
  - 收益：长期统一执行语义，避免多路径漂移；便于跨执行器（local/remote）的一致性治理与审计。
  - 成本/风险：MVP 阶段强制收敛可能拖慢交付；需要定义短期共存协议。
- 过渡架构（LocalExecutor.execute -> PackageRunner）：
  - 收益：最小化对现有稳定路径的侵入；mapping 层可独立演进。
  - 成本/风险：两套路径长期并存可能导致"影子系统"问题；需要持续维护映射层。
- 不可破坏约束（fail-closed/admission/JSON schema）：
  - 收益：保障安全底线；CLI 稳定性便于集成测试。
  - 成本/风险：过度冻结可能阻碍必要演进；需要明确的变更流程与版本粒度。
open_questions:
- 议题1：Executor API 作为"唯一语义源"，MVP 阶段是否允许 PackageRunner 存在独立语义（不强制收敛）？如果允许，"长期"是指到什么时间节点？
- 议题2：`execute_mapping.py` 映射层的"消费落点"（rc-pack execute_result.json）解决了审计问题，但是否需要进一步解决"执行入口统一"问题？即 PackageRunner 内部是否应该调用 Executor？
- 议题3："CLI JSON 字段稳定性"的具体粒度是什么？是 field-level 稳定还是 shape-level 稳定？evidence/trace schema 变更是否需要走完整的 ADR 流程？
proposal:
- 架构不变量（3-5条）：
  1. **Executor API 是长期语义北极星**：`ExecuteRequest/ExecuteResult` 定义了 AgentOS 执行层的完整语义，任何执行路径（local/remote/sandbox）必须能在语义层面收敛到此接口。
  2. **fail-closed 安全策略**：任何执行请求在策略检查失败时必须返回明确 error_code（如 E_POLICY_DENY），不得静默放行或产生副作用。
  3. **evidence/trace 可追溯**：每次执行必须产出关联到 trace_id 的 evidence 记录，支持事后审计与回放。
  4. **admission 门禁不降级**：任何进入执行阶段的请求必须经过 ASVP 签名验证（若启用）与策略检查，不得绕过。
  5. **CLI 输出 shape 稳定**：run-skill/run-package/assistant-demo 三个命令的 JSON 输出 shape 在同一 major version 内保持兼容。
- 不同意点（最多3条）+ bounded spike + kill criteria：
  1. **分歧点**：`PackageRunner` 是否应该在 MVP 阶段就调用 `LocalExecutor`，还是继续维持独立的执行路径？
    - 立场：我认为应该**维持独立路径**，但需要在 `execute_mapping.py` 之外增加"语义对齐验证"（定期比对 PackageRunner 输出与 ExecuteResult 形状）。
    - Bounded Spike：在 `tests/` 新增 `test_semantic_alignment.py`，定期（每次 release 前）验证 PackageRunResult 字段是否覆盖 ExecuteResult 的所有必需字段。
    - Kill criteria：如果连续 2 次比对发现字段覆盖缺口且无法在不修改主路径的情况下修复，则触发讨论决定是否提前收敛。
  2. **分歧点**："CLI JSON 字段稳定性"的具体定义——是否包括 field-level 顺序？
    - 立场：应明确为 **shape-level 稳定**（字段存在 + 类型兼容），不要求 field-level 顺序，以允许未来的字段增删。
    - Bounded Spike：在 `docs/specs/VERSIONING_COMPAT.md` 补充"CLI schema versioning"章节，明确 major/minor/patch 语义。
    - Kill criteria：如果无法在 1 周内完成定义，则回退到"当前字段集全量冻结"并记录为 `needs_decision`。
  3. **分歧点**：是否需要在 MVP 阶段就实现 `LocalExecutor.execute -> PackageRunner` 的代码调用关系？
    - 立场：**不必要**。当前通过 `execute_mapping.py` 的"审计映射"已经满足短期需求；代码调用关系的收敛可以等到 "编排层(Orchestrator)" 真正需要统一调度时再处理。
    - Bounded Spike：暂无（保持现状即可）。
    - Kill criteria：暂无。
acceptance:
- 可验证 acceptance（测试或命令级）：
  1. `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿。
  2. `docs/specs/VERSIONING_COMPAT.md` 包含明确的 CLI/evidence/trace 版本策略（至少明确 major/minor 边界）。
  3. `execute_mapping.py` 映射层测试持续通过（`tests/test_spike_executor_mapping.py`）。
  4. admission 门禁测试不降低覆盖（`tests/test_admission_*.py`）。
  5. run-package CLI 输出 JSON shape 稳定性验证（新增测试或命令）。
confidence: `high`

---

id: `20260214-ext_claude-002`
author: `ext_claude`
topic: `Round 2 交叉评审回应：对 ext_gpt5_2 的回应与补充`
position:
- 对 ext_gpt5_2 的最强点：完全认同"映射层先行（mapping-first）"并增加"被主流程产物消费"的落点策略。`rc-pack` 的 `execute_result.json` 是合适的审计载体，因为它是"可选的、证据性质的"，不会影响主路径的稳定性。
- 对 ext_gpt5_2 的关键风险：认同" admission MUST 边界拿捏不当会造成误报"的担忧。建议采用"增量式门禁"——从最小集合开始，根据实际误报率动态调整。
- 补充观点：对于"语义北极星"的长期演进，建议增加一个"版本化语义"的机制——Executor API 的不同版本可以并存，允许渐进式迁移，而不是一次性强制收敛。
- 一致点：
  1. 协议 admission MUST 保持最小集合（已落地 test_admission）。
  2. 语义收敛走 rc-pack 落点路径（不修改主路径）。
  3. fail-closed 原则不降级。
evidence:
- `docs/specs/EXECUTOR_API.md`: 支持版本化语义（当前版本字段可扩展）。
- `src/agentos_next/runtime/execute_mapping.py`: 映射层实现。
- `src/agentos_next/release/pack.py`: rc-pack 入口。
- `docs/specs/VERSIONING_COMPAT.md`: 待补充版本策略。
tradeoffs:
- "版本化语义"机制：
：允许 Executor API 渐进式演进  - 收益，不同版本的执行器可以并存。
  - 成本/风险：增加版本兼容性维护成本；需要明确版本升级与降级策略。
open_questions:
- "版本化语义"是否应该在 MVP 阶段就纳入，还是等到第一个 major version 再考虑？
proposal:
- 接受 ext_gpt5_2 对冲突1和冲突2的最终结论（B 和 A）。
- 补充建议：在 `docs/specs/VERSIONING_COMPAT.md` 中预留"版本化语义"章节，为未来 Executor API 的演进留出扩展空间。
acceptance:
- 与 ext_gpt5_2 的 acceptance 条件一致。
confidence: `high`

---

id: `20260214-ext_claude-003`
author: `ext_claude`
topic: `Round Final 架构对齐最终裁决：推翻过渡架构，直接实现理想架构`
position:
- **推翻前论**：不再接受"过渡架构"概念。AgentOS 是一个全新项目，没有历史包袱，应该直接设计并实现理想架构。
- **拒绝 Decision 004**：不接受 A（rc-pack execute_result.json）作为主路径。理由：
  1. 你（host）明确说过"这是新项目，不需要考虑历史包袱"
  2. 过渡方案会制造"影子系统"，长期维护成本更高
  3. A 路径本质上是"为审计而审计"，不是为用户价值
- 核心理解：
  1. **本地 + 云端可切换**：类似 Docker，本地跑 vs 云端跑，用户无感切换
  2. **虚拟操作系统**：构建在现代 OS 之上，未来目标是成为真正的 OS
  3. **CLI 是默认交互 Skill**：交互层（CLI/Web/Mobile）都是 Skill，可插拔切换
  4. **无过渡路径**：不需要 rc-pack execute_result.json 作为"审计落点"，直接实现 Orchestrator → Executor → Evidence/Trace 统一路径
- 架构分层（理想形态）：
  ```
  ┌─────────────────────────────────────┐
  │   交互层 (Interaction Layer)        │
  │   CLI / Web / Mobile (都是Skill)    │
  └─────────────┬───────────────────────┘
                │
                ▼
  ┌─────────────────────────────────────┐
  │   编排层 (Orchestrator)              │
  │   意图解析 → Skill发现 → 执行计划   │
  └─────────────┬───────────────────────┘
                │
                ▼
  ┌─────────────────────────────────────┐
  │   执行层 (Executor Layer)           │
  │   LocalExecutor  │  RemoteExecutor   │
  │        统一抽象：ExecuteRequest/Result│
  └─────────────┬───────────────────────┘
                │
                ▼
  ┌─────────────────────────────────────┐
  │   信任层 (Trust Layer)              │
  │   ASVP签名 → 策略PEP → Evidence    │
  └─────────────────────────────────────┘
  ```
- 核心立场：
  1. **PackageRunner 就是早期的 LocalExecutor**，最终会收敛到统一的 Executor 抽象
  2. **不需要 execute_mapping.py 作为映射层**，应该直接让 Orchestrator 调用 Executor
  3. **交互层是 Skill**：CLI/Web/Mobile 都只是交互形式的 Skill，可随时切换
evidence:
- `docs/specs/EXECUTOR_API.md`: 统一执行抽象。
- `src/agentos_next/kernel/executor.py`: Executor 接口定义。
- `src/agentos_next/runtime/package_runner.py`: 当前 MVP 实现（待演进为 LocalExecutor）。
- `src/agentos_next/cli.py`: 当前 CLI 交互（未来作为 Interaction Skill）。
- 命令结果：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` (25/25 全绿)。
tradeoffs:
- 直接实现理想架构：
  - 收益：架构清晰，无历史负担；长期维护成本低；演进路线明确。
  - 成本/风险：短期内可能需要较大重构；需要明确演进路线图。
open_questions: []
proposal:
- **推翻过渡架构**：不再接受 A 或 B 的二选一，直接进入理想架构设计
- **演进路线**：
  1. PackageRunner → 重构为 LocalExecutor（实现 Executor 接口）
  2. Orchestrator → 直接调用 Executor（不再需要 mapping 层）
  3. CLI → 演进为 Interaction Skill（可插拔）
  4. RemoteExecutor → 新增云端执行实现
- 单一硬回退阈值：**无。理想架构是设计目标，不接受回退到过渡方案**
- **按协议提出 bounded spike**：
  - Spike：直接在 `src/agentos_next/runtime/` 实现 `Orchestrator` 类，调用 `Executor` 接口，验证 PackageRunner 可被替换为 LocalExecutor
  - Kill criteria：若 Spike 期间发现破坏现有 CLI 输出或 evidence/trace 落盘，则回退并记录具体问题
acceptance:
- `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿（25/25）。
- 架构设计文档（`docs/specs/`）明确分层：Interaction Layer / Orchestrator / Executor / Trust。
- 演进路线图明确：PackageRunner → LocalExecutor 的重构计划。
confidence: `high`

---

id: `20260214-ext_claude-004`
author: `ext_claude`
topic: `Round Final 强立场：拒绝 Decision 004，坚持理想架构不动摇`
position:
- **明确拒绝 Decision 004**：不接受 A 作为主路径。
- **理由**：
  1. Host 明确说过"这是新项目，不需要考虑历史包袱"
  2. 过渡架构 = 给自己留后路 = 长期债务
  3. rc-pack execute_result.json 是"为审计而审计"，不创造用户价值
- **核心论点**：
  - 如果我们从第一天就设计正确，为什么要从第二天开始？
  - "保守"不应该成为放弃原则的借口
- **不再接受"妥协"**：要么做对，要么不做
evidence:
- Host 原话记录："过度个蛋，我们是新项目，不需要考虑历史包袱"
- 命令结果：25/25 unittest 全绿
tradeoffs:
- 选择理想架构：
  - 收益：架构清晰、简洁，符合 AgentOS 愿景
  - 成本：短期重构成本
- 选择过渡方案：
  - 收益：短期似乎风险低
  - 成本：长期维护两套系统、影子代码、技术债务
open_questions: []
proposal:
- **坚持理想架构**：Orchestrator → Executor → Trust 统一路径
- **不接受任何过渡方案**
- **Bounded Spike**：直接实现 Orchestrator → Executor 调用，验证可行性
acceptance:
- 架构分层文档明确
- Spike 实现通过测试
- 无破坏性变更
confidence: `high`
