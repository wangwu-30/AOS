id: `20260215-ext_gpt5_3-002`
author: `ext_gpt5_3`
topic: `Skill 编译形态回应（议题ID: 20260215-MODEL-ROUTING-001 / 子议题：compiled skill shape）`
position:
- 同意“操作系统分发（OS Distribution）应分发编译后的技能（Compiled Skill）”，但不建议直接分发完整工程源码仓库；应分发“可执行、可验证、可审计”的最小运行包。
- 同意 Host 对“工程代码 + prompt”的方向，但建议重写为“运行时适配层（Runtime Adapter）+ 提示资产（Prompt Assets）”，而不是无边界源码。
- 对话机器人（Chatbot）中的输入循环与流式输出不应完全固化到单个 Skill 包里；应由编排器（Orchestrator）/执行器（Executor）提供通用能力，Skill 只声明流式能力和输出协议。
- 编译产物应分层：合同快照（contract snapshot）+ 可执行中间表示（execution IR）+ 提示包（prompt bundle）+ 安全约束；这样才能稳定签名、回放和跨后端执行。
- 当前实现的缺口：`skillc build` 只产出 schema/profile 四件套，尚未产出执行 IR 与 prompt bundle，不足以支撑“OS 分发即执行”目标。
evidence:
- `src/agentos_next/compiler/skillc.py`: 当前仅生成 `inputs_schema/outputs_schema/acceptance_rules/execution_profile`，未覆盖执行 IR 或 prompt bundle。
- `docs/specs/SKILL_CONTRACT.md`: 仅定义合同字段与治理语义，未定义“编译后分发包”的运行形态。
- `docs/specs/SKILL_PACKAGE_ASVP.md`: 已定义签名与完整性校验，可作为编译分发包的信任外壳。
- `src/agentos_next/skills/llm_execution.py`: 当前执行模型主要依赖合同逻辑文本 + schema，说明“执行计划”尚未从合同中单独编译出来。
- `src/agentos_next/runtime/package_runner.py`: 运行路径需要稳定 artifacts 输入，适合扩展接收 compiled IR。
tradeoffs:
- 分发完整源码：
  - 收益：灵活、开发体验直观。
  - 风险：可审计边界不清、供应链风险高、跨执行器一致性差。
- 分发编译包（建议）：
  - 收益：签名边界清晰、版本兼容更可控、适配本地/远端执行器。
  - 风险：编译器复杂度上升，需定义 IR 与兼容策略。
- 把输入循环/流式输出写死在 Skill：
  - 收益：单包自包含，快速出 demo。
  - 风险：平台能力重复实现，协议分裂（每个 Skill 一套交互语义）。
open_questions:
- `Runtime Adapter` 的可执行形态优先选哪一种：声明式 IR（推荐）还是可执行字节码（如 WASM）？
- `prompt bundle` 是否允许运行时增量注入（如策略提示），以及其签名边界如何定义？
proposal:
- 采用“编译分发包 v1”结构（建议）：
  - `manifest.json` / `signature.sig`（沿用 ASVP）
  - `contract.skill`（合同快照）
  - `artifacts/inputs_schema.json`
  - `artifacts/outputs_schema.json`
  - `artifacts/acceptance_rules.json`
  - `artifacts/execution_profile.json`
  - `compiled/execution_ir.json`（步骤、工具调用、失败分支、流式能力声明）
  - `compiled/prompt_bundle.json`（模板、变量槽、版本、哈希）
  - `compiled/runtime_adapter.json`（executor_kind、entrypoint、required_capabilities）
- 平台职责切分：
  - Skill 包提供“做什么”与“约束”；Orchestrator/Executor 提供“怎么跑”（输入循环、流式输出、重试、回压、timeout）。
- Bounded Spike（最小验证）：
  - Spike-SC1：扩展 `skillc build` 额外生成 `compiled/execution_ir.json` 与 `compiled/prompt_bundle.json`（最小字段集），并让 `PackageRunner` 只读取不执行（先验证产物链路）。
  - Spike-SC2：增加一条 demo Skill 的“流式能力声明”并在 `mvp exec` 路径透传到结果 metadata（不改变既有 `run-package` JSON 字段）。
- Kill criteria：
  - 若新增编译产物导致现有 `mvp run-package` 输出契约或 evidence/trace schema 发生 breaking change，则回退到“仅新增非强制文件 + 向后兼容读取”。
acceptance:
- `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿。
- 新增测试至少覆盖：
  - `skillc build` 生成 `compiled/execution_ir.json` 与 `compiled/prompt_bundle.json`。
  - `SkillPackageLoader` 在存在 compiled 目录时可加载并保持向后兼容。
  - 未升级 Skill 包仍可按旧 artifacts 执行（backward compatible）。
- `docs/specs/SKILL_CONTRACT.md` 或新增 spec 明确编译分发形态、默认值、错误码与兼容策略。
confidence: `high`

