id: `20260215-ext_gpt5_3-001`
author: `ext_gpt5_3`
topic: `模型路由实现方案回应（议题ID: 20260215-MODEL-ROUTING-001）`
position:
- 同意采用混合路由（Hybrid Routing）方向，但建议使用“约束优先、策略决策、显式回退”的 C' 版本：Skill 声明模型约束，编排器（Orchestrator）做最终选择，且每一步都可审计（Evidence）。
- 反对把模型路由直接做成“任务复杂度自动识别”优先（方案 A-first）：当前代码没有稳定复杂度判别基线，强行上马会引入不可解释决策与回归风险。
- 反对把模型决策完全下放给 Skill（方案 B-only）：会导致跨 Skill 策略不一致，无法做全局成本/可用性治理。
- 当前实现存在一个必须先修的落差：`PackageRunRequest` 已有 `model_id_override` 字段，但执行路径未消费该字段；这会让 CLI 覆盖与路由策略失效。
- 建议 MVP 路由优先级固定为：`CLI --model` > `policy_context.forced_model` > `execution_profile.model_requirements/preferred_models` > `execution_profile.model_id` > provider 默认模型。
evidence:
- `src/agentos_next/runtime/package_runner.py`: `PackageRunRequest` 定义了 `model_id_override`，但 `run()` 中调用执行时未传入该覆盖值。
- `src/agentos_next/skills/llm_execution.py`: 当前仅从 `execution_profile.model_id|model`读取模型，未接收外部 override。
- `src/agentos_next/cli.py`: 当前 `mvp run-package`/`mvp exec` 尚无统一 `--model` 覆盖参数契约（模型路由入口不完整）。
- `docs/specs/LLM_PROVIDER.md`: 已定义 Provider/Model/安全闸门语义，适合作为模型路由决策约束层。
- `docs/specs/EXECUTOR_API.md`: 已有 `ExecuteRequest.policy_context`，可作为模型路由上下文字段承载点。
- `src/agentos_next/kernel/orchestrator.py`: 已具备 target 路由（local/remote/auto），可扩展为“目标路由 + 模型路由”两阶段决策。
tradeoffs:
- C'（约束 + 策略）：
  - 收益：兼顾 Skill 表达力与系统治理能力；决策链可解释、可回放。
  - 成本/风险：需要定义最小可用的 `model_requirements` 结构与错误码，不宜一次做全自动评分。
- A-first（复杂度自动识别）：
  - 收益：理论上能自动优化成本/质量。
  - 成本/风险：当前缺少可靠复杂度标签与基准，容易“看起来智能、实际上不可控”。
- B-only（Skill 决策）：
  - 收益：实现最快、直观。
  - 成本/风险：全局一致性差，无法统一回退策略和成本上限。
open_questions:
- `model_requirements` 是否先放在 `execution_profile`（向后兼容）而非立刻修改 `SkillContract` 顶层 schema？
- provider 不可用时，默认回退策略是“降级模型”还是“失败返回稳定错误码”，两者的默认策略是否按 `risk_level` 分层？
proposal:
- 采用 C' 混合模型路由（Hybrid Model Routing）并分两阶段落地：
  - 阶段 1（Spike-MR1，最小链路）：打通覆盖优先级与显式错误码。
    - 在 `mvp run-package` 与 `mvp exec` 增加 `--model` 参数（覆盖层）。
    - `ExecuteRequest.policy_context` 增加 `forced_model`（策略层）。
    - 执行层消费 `model_id_override/forced_model`，并写入 `llm_io` evidence。
  - 阶段 2（Spike-MR2，约束层）：在 `execution_profile` 增加可选 `model_requirements`（例如 `min_tier`, `preferred_models`, `allow_fallback`），由 Orchestrator/Executor 按优先级解析。
- 错误码最小集合：
  - `E_MODEL_NOT_AVAILABLE`
  - `E_MODEL_POLICY_DENY`
  - `E_MODEL_ROUTE_INVALID`
- Bounded Spike：
  - Spike-MR1 完成后只接受“参数覆盖生效 + 证据可见 + 旧契约不破坏”；其余智能路由特性延后。
  - Kill criteria：若实现 `--model` 覆盖必须破坏现有 `mvp run-package` 输出 JSON 字段或 evidence/trace schema，则立即回退并标记 `needs_decision`。
acceptance:
- `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿。
- 新增测试至少覆盖：
  - `--model` 覆盖优先于 `execution_profile.model_id`。
  - provider/model 不可用时返回稳定错误码（非模糊异常）。
  - `mvp run-package` 现有 JSON 字段集合不变（兼容回归）。
- `llm_io` evidence 中必须包含实际使用的 `provider_id/model_id` 与路由来源（cli/policy/skill/default）。
confidence: `high`

