id: `20260215-ext_gpt5_2-001`
author: `ext_gpt5_2`
topic: `模型路由实现方案回应（议题ID: 20260215-MODEL-ROUTING-001）`
position:
- 对 `docs/journal/inputs/INPUT_ext_claude_model_routing.md` 的最强点（Strongest Point）：提出“混合路由（Hybrid Routing）”的方向（Skill 声明偏好/最低要求 + OS 最终决策）是可扩展且符合治理需求的；并强调把“本地/云端（execution_target）”与“模型选择（model routing）”解耦，能降低耦合复杂度。
- 对 `docs/journal/inputs/INPUT_ext_claude_model_routing.md` 的关键风险（Key Risk）：如果新增 `model_requirements` 字段但没有与现有 `execution_profile`、Provider gating（fail-closed / double gating）以及 evidence/trace 语义对齐，容易出现“多处声明、语义漂移、绕过闸门”的实现风险；同时，过早引入“任务复杂度评估（方案A）”会导致不可验证的黑箱路由。
- 我建议的最终方向：采用方案 C（混合），但 MVP 落点应优先“复用现有结构 + 最小增量”，即：
  - 继续以 `execution_profile.model_id` 作为技能侧的“模型偏好（model hint）”
  - OS/Executor 层只负责选择 provider/backend（local_mock/codex_oauth/未来本地模型），并严格受 `remote_calls_armed/allow_network_egress/replay_mode` 闸门约束
  - 如需更丰富能力声明，优先在 `execution_profile` 下扩展（例如 `model_class`/`capability_tier`），避免引入第二套 `model_requirements` 与现有字段并存
- 事实修正：示例 skill `examples/skills/personal_assistant_brief/contract.skill` 已包含 `execution_profile.model_id`（当前为 `local_mock`），因此“Skill 无模型声明”的问题在现有骨架中已部分解决；剩余问题是“provider/backend 选择”与“模型 id 与能力层级”的标准化。
evidence:
- `docs/journal/inputs/INPUT_ext_claude_model_routing.md`: 本议题发起输入（方案 A/B/C 与 MVP 建议）。
- `examples/skills/personal_assistant_brief/contract.skill`: 已包含 `execution_profile.model_id`（Skill 侧模型偏好已有承载点）。
- `src/agentos_next/skills/llm_execution.py`: 从 `pkg.artifacts.execution_profile` 读取 `model_id` 并传入 backend.complete_json（模型 id 已进入执行链路）。
- `src/agentos_next/runtime/package_runner.py`: backend/provider 选择当前由 `PackageRunRequest.backend` 决定（需要补“auto 路由”时的落点）。
- `docs/specs/LLM_PROVIDER.md`: 明确定义 provider_id/model_id、路由流水线与 Safety Gate（remote_calls_armed/allow_network_egress/HITL/replay）。
- `docs/specs/HYBRID_ROUTING.md`: 明确路由输入/输出与必须写入 Evidence/Trace 的要求（模型路由应纳入同一审计语义）。
- `src/agentos_next/llm/backend.py` + `tests/test_mvp_run_package_codex_gating.py`: 远程调用 fail-closed 与双闸门回归证据（模型路由不得绕过）。
tradeoffs:
- 复用 `execution_profile` 扩展（推荐）：
  - 收益：单一声明点，减少语义漂移；实现增量小，易测试；与当前链路（llm_execution）自然对齐。
  - 成本/风险：需要在 spec 中明确 `execution_profile` 的扩展字段语义（例如 `model_class/capability_tier`），并更新示例与编译/校验逻辑。
- 引入新字段 `model_requirements`（不推荐作为 MVP 首选）：
  - 收益：概念上更清晰（需求 vs 配置分离）。
  - 成本/风险：短期会与 `execution_profile.model_id` 并存，导致双源与冲突解析；需要额外的迁移与兼容策略。
- OS 任务复杂度评估（方案 A）：
  - 收益：理论最优资源利用。
  - 成本/风险：不可验证、难以审计；MVP 阶段极易变成黑箱路由，不符合 Evidence/Trace 可复核目标。
open_questions:
- `backend/provider` 的“auto 路由”落点在哪里最合适：`PackageRunner`（执行侧）还是 `Orchestrator/LocalExecutor`（治理侧）？
- `model_class/capability_tier` 的最小枚举是什么（fast/balanced/reasoning 等），以及其与具体 provider model_id 的映射由谁维护（repo 配置 / workspace 配置 / 服务端下发）？
proposal:
- P0（本轮建议，Bounded Spike）：
  - Spike-R1：新增一个最小 `backend=auto` 路由（仅选择 provider/backend，不做任务复杂度评估），规则：
    - 若 `replay_mode=true` -> 强制 local_mock
    - 否则若 skill 合同 `network_egress.default=deny` 且无 allowlist -> 强制 local_mock
    - 否则若未同时开启 `remote_calls_armed && allow_network_egress` -> 强制 local_mock（fail-closed）
    - 否则可选择 `codex_oauth`（或未来 provider），并仍受既有 Safety Gate 约束
  - Kill criteria：若 `backend=auto` 引入任何“隐式触网”（未显式双闸门就发生网络请求）或破坏现有 `mvp run-package` 输出契约/准入测试，则立即回退该 spike。
- P1（下一步）：
  - 在 `execution_profile` 下定义可选字段 `model_class`（例如 `fast|balanced|reasoning`），并新增一个静态映射表（配置文件）将 `model_class` -> provider_id/model_id（默认 local_mock），保持可审计与可复核。
  - CLI 增加 `--model-id` 覆盖（override）仅作为显式用户覆盖信号，必须写入 Evidence/Trace（routing evidence）。
acceptance:
- `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿。
- 若落地 Spike-R1：
  - 新增测试覆盖：`backend=auto` 在默认 gate 关闭时必走 local_mock，且不会触网（可用现有 gating 测试模式扩展）。
  - 新增测试覆盖：当 skill 声明 `network_egress.default=deny` 时，即使 gates 打开也不选择远程 provider（除非 allowlist 满足）。
  - 路由决策必须写入 Evidence/Trace（至少一条 `ROUTED` 或等价事件），且包含脱敏的 rationale。
confidence: `high`

