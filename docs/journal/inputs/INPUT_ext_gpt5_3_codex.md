id: `20260214-ext_gpt5_3_codex-001`
author: `ext_gpt5_3_codex`
topic: `agentos-next 深度分析与优先改进建议（架构/安全/工程）`
position:
- 当前 MVP 架构主线正确，`PackageRunner -> LLMBackend -> Evidence/Trace` 形成了可验证闭环，但执行语义与“正式 Executor 接口（`ExecuteRequest/ExecuteResult`）”存在并行路径，后续扩展阶段存在语义漂移风险。
- 安全基线（fail-closed + double gating + ASVP）已具备，但“协作文档流程”和“发布准入门”尚未形成自动化耦合，存在流程层绕过风险。
- 工程交付链路可用（22/22），但 release 证据包对协作决策上下文未纳入，导致“为什么这样改”的审计链不完整。
evidence:
- `src/agentos_next/runtime/package_runner.py`: 已实现风险分级、HITL gate、pre/post-check、evidence/trace。
- `src/agentos_next/kernel/executor.py`: 定义了更通用的 `ExecuteRequest/ExecuteResult`，但尚未成为当前包执行主路径。
- `src/agentos_next/llm/backend.py`: codex 后端在调用前执行 replay/HITL/double-gating，错误码稳定。
- `src/agentos_next/release/pack.py`: `mvp release-pack` 包含 admission 与 demo/trace，但未关联协作线程输入/决策 refs。
- 命令结果：`PYTHONPATH=src python3 -m unittest discover -s tests -v`，22/22 通过。
tradeoffs:
- 收益：先固化协作协议可显著降低多专家沟通熵，避免重复分析与无证据争论。
- 风险：若不将协议校验接入 admission tests，协议可能退化为“文档存在但流程不执行”。
- 收益：将协作决策 refs 纳入 release pack 可提升审计可追溯性，降低后续架构争议复盘成本。
- 风险：过早收敛 Runtime/Executor 统一接口会增加短期重构成本，影响 MVP 迭代速度。
open_questions:
- 是否在下一阶段将 `PackageRunner` 结果结构向 `ExecuteResult` 语义收敛（至少在字段层做映射）？
- 是否将“协作协议合规”提升为 admission tests 的 MUST 项，而非仅文档约定？
proposal:
- P0（本轮）：新增并落地 `docs/specs/EXPERT_COLLAB_PROTOCOL.md` 与线程文件，形成可执行协作骨架。
- P1（下轮）：新增 admission tests，校验 `INPUT_<expert>.md` 字段完整性与 `SYNTHESIS` 状态机约束。
- P1（下轮）：扩展 `mvp release-pack`，增加 `collab_refs` 字段（thread/synthesis/decisions 文件引用）。
- P2（后续）：设计 `PackageRunResult -> ExecuteResult` 映射规范，减少双语义路径长期分叉。
acceptance:
- `docs/specs/EXPERT_COLLAB_PROTOCOL.md` 存在且包含默认值、错误码、边界条件、兼容策略、测试与验收。
- 线程文件与 `INPUT_ext_gpt5_3_codex.md`、`SYNTHESIS_<thread_id>.md`、`DECISIONS_<thread_id>.md` 成套存在。
- 后续若实施 P1：新增 admission 用例可在缺字段输入时给出失败结论（对应 `E_PROTOCOL_SCHEMA_INVALID`）。
confidence: `high`
