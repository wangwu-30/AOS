# 技能创作者（Skill Creator）规范

- 状态（Status）：Draft
- 日期（Date）：2026-03-13
- 相关规范（Related Specs）：
  - `docs/specs/SKILL_CONTRACT.md`
  - `docs/specs/MVP_056_LOCAL_UNSIGNED_SKILL_AND_COMPAT.md`
  - `docs/specs/EXECUTOR_API.md`

## 目的（Purpose）

定义 `skill-creator` 的最小规范，使其既能做仅规划不执行（plan-only）的技能生成规划，也能产出本地未签名技能（Local Unsigned Skill），并保证产物不会进入正式技能中心（Skill Hub）。

## 范围（Scope）

本规范涵盖：

- `builtin://creator.plan`
- `builtin://creator.write_local_skill`
- 默认值、错误码、边界条件、兼容策略与测试验收

本规范不涵盖：

- 正式 hub 发布流程
- 自动签名
- 自动上线 registry

## 核心概念（Concepts）

- 技能规划（Creator Plan）：仅输出组合计划，不执行技能创建动作。
- 本地未签名技能（Local Unsigned Skill）：skill-creator 的默认产物类型。
- 本地技能层（Local Skill Layer）：默认落盘到 `.agentos/local_skills/` 的独立层。

## 接口/数据结构（Interfaces/Data）

### `builtin://creator.plan`

输入必须（MUST）至少包含：

- `intent` 或 `request`

输出必须（MUST）至少包含：

- `schema_version`
- `ok`
- `registry_root`
- `plan`

`plan` 必须（MUST）满足：

- `mode=plan_only`
- 包含 `steps[]`
- 每个 `steps[i]` 包含可映射到 `ExecuteRequest` 的 `execute_request` 草案

### `builtin://creator.write_local_skill`

输入必须（MUST）至少包含：

- `name`
- `description`
- `logic`

输出必须（MUST）至少包含：

- `schema_version`
- `ok`
- `skill_dir`
- `fingerprint`
- `skill_ref`
- `unsigned_local_skill=true`
- `skill_layer=local_unsigned`
- `registry_eligible=false`

产物目录必须（MUST）包含：

- `contract.skill`
- `artifacts/inputs_schema.json`
- `artifacts/outputs_schema.json`
- `artifacts/acceptance_rules.json`
- `artifacts/execution_profile.json`

## 默认值（Defaults）

- `workspace_id` 默认值必须（MUST）为 `local`
- `deadline_ms` 默认值必须（MUST）为 `60000`
- `max_steps` 默认值必须（MUST）为 `3`
- `version` 默认值必须（MUST）为 `0.1.0`
- `risk_level` 默认值必须（MUST）为 `low`
- 未显式传入 `skill_dir` 时，产物默认必须（MUST）写入 `<registry_root or cwd>/.agentos/local_skills/<skill_name>`

## 语义与边界条件（Semantics/Boundary Conditions）

- `creator.plan` 必须（MUST）是确定性的：相同输入与相同 registry 快照应产出相同计划。
- `creator.plan` 必须（MUST NOT）触发真实执行。
- `creator.write_local_skill` 必须（MUST）只产出本地 unsigned skill。
- `creator.write_local_skill` 不得（MUST NOT）把产物写入正式 hub canonical 目录。
- `creator.write_local_skill` 若目标目录非空且 `overwrite=false`，必须（MUST）失败。
- 产物 `contract.skill` 必须（MUST）显式声明 `type=local_unsigned_skill_v1`。

## 错误与重试（Errors/Retry）

系统必须（MUST）使用稳定错误码：

- `E_CREATOR_REGISTRY_INVALID`
- `E_CREATOR_SCHEMA_UNSUPPORTED`
- `E_CREATOR_COMPOSE_INVALID`
- `E_CREATOR_SKILL_INVALID`
- `E_CREATOR_SKILL_EXISTS`

重试语义（MUST）：

- `E_CREATOR_SKILL_EXISTS` 仅在显式 `overwrite=true` 时可以（MAY）通过重试覆盖
- 其余 schema / 参数错误在输入修正前不得（MUST NOT）自动重试

## 安全与隐私（Security/Privacy）

- `creator.write_local_skill` 必须（MUST）要求 `fs_write` 能力。
- skill-creator 产物默认不得（MUST NOT）声明网络外发；若要声明，必须（MUST）显式写入 contract。

## 可观测性（Observability）

必须（MUST）记录：

- `skill_dir`
- `fingerprint`
- `skill_layer`
- `registry_eligible`
- creator 输出 evidence

## 兼容与版本（Compatibility/Versioning）

- `creator.plan` 的 plan-only 输出不得（MUST NOT）破坏现有 `ExecuteRequest` 映射。
- `creator.write_local_skill` 为 additive change；不得（MUST NOT）改变现有正式 skill 的 contract 或 ASVP 语义。

## 测试与验收（Tests/Acceptance）

必须（MUST）覆盖以下场景：

1. `creator.plan` 输出 `plan_only`
2. `creator.write_local_skill` 把技能写入 `.agentos/local_skills`
3. 写出的产物包含 `contract.skill` 与 `artifacts/*`
4. 产物元数据包含 `skill_layer=local_unsigned` 与 `registry_eligible=false`

验收命令（MUST）：

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread047_runtime_capabilities_and_web.TestThread047RuntimeCapabilitiesAndWeb.test_builtin_creator_plan_returns_skill_first_plan -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread047_runtime_capabilities_and_web.TestThread047RuntimeCapabilitiesAndWeb.test_builtin_creator_write_local_skill_uses_local_unsigned_layer -v`
