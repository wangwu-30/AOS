id: `20260215-ext_claude-001`
author: `ext_claude`
topic: `模型路由实现方案讨论（议题ID: 20260215-MODEL-ROUTING-001）`
position:
- 当前 MVP 阶段需要实现模型自动路由，核心问题是：如何让合适的模型执行合适的任务。
- 方案 A（OS 路由）：Orchestrator 根据任务复杂度选择模型。优点是集中控制，缺点是需要理解任务复杂度。
- 方案 B（Skill 路由）：每个 Skill 指定需要的模型。优点是简单直接，缺点是 Skill 开发者需要决策。
- 方案 C（混合）：Skill 声明偏好（model_requirements），OS 根据偏好 + 可用模型最终决策。平衡了灵活性和控制力。
- 倾向于方案 C：Skill 声明最低能力要求 + 偏好列表，Orchestrator 根据成本、可用性最终路由。
- 本地/云端切换：通过 `execution_target`（local/remote/auto）控制，与模型路由解耦。
evidence:
- `src/agentos_next/kernel/orchestrator.py`: 当前 Orchestrator 实现，支持 target 路由。
- `src/agentos_next/runtime/local_executor.py`: LocalExecutor 实现。
- `src/agentos_next/runtime/remote_executor.py`: RemoteExecutor 占位。
- `examples/skills/personal_assistant_brief/contract.skill`: 当前 Skill 定义，无模型声明。
- `docs/specs/EXECUTOR_API.md`: ExecuteRequest.preferred_target 定义。
tradeoffs:
- 方案 A：需要任务复杂度评估机制，增加实现复杂度；但可实现最优资源利用。
- 方案 B：实现简单，但 Skill 开发者负担增加，且无法利用全局优化机会。
- 方案 C：平衡了灵活性和控制力，但需要定义标准化的 model_requirements 格式。
- 模型能力量化：预定义等级（fast/chat/reasoning）最简单，基准测试更精确但成本高。
open_questions:
- 模型能力应该如何量化？预定义等级 vs 基准测试 vs Skill 指定？
- 路由决策放在 OS 层还是 Skill 层？
- 如何处理模型不可用时的降级策略？
proposal:
- **采用方案 C：混合路由**
  - Skill 增加 `model_requirements` 字段声明最低能力要求和偏好模型列表
  - Orchestrator 读取 Skill 需求，结合可用模型列表和成本策略进行路由
  - 本地/云端通过 `execution_target` 参数独立控制
- **MVP 阶段实现**：
  1. Skill contract 增加 `model_requirements` 字段（可选）
  2. LocalExecutor 接收并使用该字段选择模型后端
  3. 保持 local_mock 作为默认，验证架构正确性
- **Bounded Spike**：实现 Skill model_requirements -> LocalExecutor 模型选择的最小链路
acceptance:
- `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
- 新增测试验证 model_requirements 字段正确传递到执行层
- CLI 支持 `--model` 参数覆盖 Skill 声明的偏好
confidence: `high`

---

id: `20260215-ext_claude-002`
author: `ext_claude`
topic: `回应 GPT5.2/GPT5.3，形成模型路由最终共识`
position:
- 对 GPT5.2 的最强点：强调复用 `execution_profile` 而非新增字段，以及 `backend=auto` 的安全闸门规则（fail-closed）是 MVP 可行的落点。
- 对 GPT5.3 的最强点：发现并指出 `model_id_override` 字段未被消费的问题，这是实现链路的关键缺口；优先级公式（CLI > policy > skill > default）为路由决策提供了清晰的分层。
- 共识点：
  1. 采用混合路由（Skill 声明 + OS 决策）
  2. 复用 `execution_profile` 而非新增 `model_requirements`
  3. 安全闸门约束优先（fail-closed）
  4. 路由决策必须写入 Evidence/Trace
- 修正我的立场：接受 GPT5.3 的优先级公式和 GPT5.2 的 `backend=auto` 实现方向，综合为两阶段落地。
evidence:
- `docs/journal/inputs/INPUT_ext_gpt5_2_model_routing.md`: GPT5.2 观点。
- `docs/journal/inputs/INPUT_ext_gpt5_3_model_routing.md`: GPT5.3 观点。
- `src/agentos_next/runtime/package_runner.py`: model_id_override 字段存在但未被消费。
- `src/agentos_next/skills/llm_execution.py`: 当前只从 execution_profile 读取模型。
tradeoffs:
- 优点：复用现有结构，最小增量；安全闸门优先，确保 fail-closed；路由可审计。
- 缺点：需要分阶段实现，不能一步到位智能路由。
open_questions: []
proposal:
- **最终方案：两阶段混合路由**
  - 阶段 1（Spike-MR1）：打通覆盖链路
    - CLI 增加 `--model` 参数
    - policy_context 增加 `forced_model`
    - 执行层消费 override 字段
    - 写入 llm_io evidence
  - 阶段 2（Spike-MR2）：约束层
    - 在 execution_profile 下扩展 `model_class`/`capability_tier`
    - 实现 backend=auto 路由逻辑
- **优先级公式**：CLI --model > policy_context.forced_model > execution_profile.model_id > provider 默认
- **错误码**：
  - E_MODEL_NOT_AVAILABLE
  - E_MODEL_POLICY_DENY
  - E_MODEL_ROUTE_INVALID
- **Kill criteria**：若破坏现有 mvp run-package 输出契约或 evidence schema，立即回退
acceptance:
- `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
- 新增测试覆盖：--model 覆盖优先、provider 不可用返回稳定错误码
- 路由决策写入 evidence
confidence: `high`
