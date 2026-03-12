# MVP_056_LOCAL_UNSIGNED_SKILL_AND_COMPAT

- 状态（Status）：Draft
- 日期（Date）：2026-03-13
- 目标版本（Target）：MVP_056
- 相关规范（Related Specs）：
  - `docs/specs/SKILL_CONTRACT.md`
  - `docs/specs/SKILL_PACKAGE_ASVP.md`
  - `docs/specs/SKILL_CREATOR.md`
  - `docs/specs/EXECUTOR_API.md`
  - `docs/specs/MVP_055_KERNEL_EXECUTION_LANE_AND_TASK_AMENDMENT.md`

## 目的（Purpose）

定义本地未签名技能（Local Unsigned Skill）与正式技能中心（Skill Hub）的分层边界，冻结 skill-creator、外部技能兼容（External Skill Compatibility）与 MCP 适配（MCP Adapter）的最小规范，保证内核 primitive 不被外部 skill transport 稀释。

## 范围（Scope）

本规范只覆盖：

- 本地未签名技能（Local Unsigned Skill）的目录、合同、批准与执行语义
- `skill-creator` 产出本地 unsigned skill 的合同
- 外部 `Agent Skills` 的运行时兼容边界
- `MCP` 通过 adapter 映射到统一 operator ABI 的边界

本规范不覆盖：

- 正式 hub 的发布工作流细节
- 第三方 registry 协议设计
- MCP transport 协议自身的标准化

## 核心概念（Concepts）

- 正式技能中心（Skill Hub）：只容纳标准 `AgentOS Skill`、具备 `registry://` 标识与 ASVP 治理链路的 canonical 集合。
- 本地未签名技能（Local Unsigned Skill）：与标准 skill 结构兼容、但位于独立本地层并跳过 ASVP 验签的技能包。
- 技能指纹（Skill Fingerprint）：对 skill 目录内容做稳定哈希后的版本标识，用于 remember-by-fingerprint 批准。
- 兼容技能适配器（Agent Skills Adapter）：将外部 `Agent Skills` 映射为运行时 operator ABI 的兼容层。
- MCP 适配器（MCP Adapter）：将 MCP provider 暴露为统一 operator ABI 的兼容层。

## 接口/数据结构（Interfaces/Data）

### Local Unsigned Skill 目录

本地未签名技能默认目录必须（MUST）位于：

- `<workspace>/.agentos/local_skills/<skill_name>`

本地 unsigned skill 的输出元数据必须（MUST）包含：

- `skill_layer=local_unsigned`
- `registry_eligible=false`
- `fingerprint`
- `skill_dir`

### Contract 与产物

本地未签名技能必须（MUST）继续使用：

- `contract.skill`
- `artifacts/inputs_schema.json`
- `artifacts/outputs_schema.json`
- `artifacts/acceptance_rules.json`
- `artifacts/execution_profile.json`

`contract.skill` 必须（MUST）保持与标准 skill contract 兼容，并显式声明：

- `type=local_unsigned_skill_v1`

### Approval Memory

remember-by-fingerprint 批准日志必须（MUST）写入：

- `data/kernel/local_skill_approvals.jsonl`

批准事件至少必须（MUST）包含：

- `type=local_skill_approval_event`
- `status`
- `approval_mode`
- `fingerprint`
- `skill_dir`

### Compat Operator ABI

外部 `Agent Skills` 与 MCP provider 必须（MUST）通过 adapter 暴露为与 `ExecuteRequest` 兼容的 operator ABI。

worker 不得（MUST NOT）直接看到：

- MCP transport
- MCP session
- 外部 Agent Skills 的私有 transport/session 对象

## 默认值（Defaults）

- 本地 unsigned skill 批准模式默认值必须（MUST）为 `once`
- 显式声明 `local_skill_approval_mode=remember_by_fingerprint` 时，批准必须（MUST）绑定 fingerprint，而不是路径名
- compat skill 若未声明只读效果，`effect_class` 默认值必须（MUST）保守推断为非 `read_only`
- `skill_exec` 且无 `allowed_operator_refs` 时，默认 `effect_class` 必须（MUST）为 `external_effect`

## 语义与边界条件（Semantics/Boundary Conditions）

### Skill Hub 与 Local Layer 分层

正式技能中心必须（MUST）只容纳：

- `registry://` 标识的 skill
- 通过 ASVP 验签的 skill
- 满足发布治理的 skill

本地 unsigned skill：

- 必须（MUST）位于独立本地层
- 不得（MUST NOT）进入正式 hub canonical 集合
- 不得（MUST NOT）伪装成 `registry://` skill

### Validation 与 Admission

本地 unsigned skill 仅可以（MAY）跳过：

- ASVP 验签

本地 unsigned skill 不得（MUST NOT）跳过：

- contract/schema 校验
- compile 产物检查
- policy gate
- execution approval

### Approval

批准语义必须（MUST）限制为：

- `once`
- `remember_by_fingerprint`

当 skill 内容变化导致 fingerprint 变化时：

- 之前的 remember-by-fingerprint 批准必须（MUST）失效
- 系统必须（MUST）重新要求批准

### Skill Creator

`skill-creator` 必须（MUST）产出本地 unsigned skill，而不是正式 hub skill。

`skill-creator` 产物必须（MUST）：

- 落在本地 unsigned layer
- 带 `skill_layer=local_unsigned`
- 带 `registry_eligible=false`

`skill-creator` 产物可以（MAY）随后被发现、加载、批准与执行，但其治理级别不得（MUST NOT）自动提升为 hub canonical skill。

### External Agent Skills Compatibility

外部 `Agent Skills` 可以（MAY）运行时兼容，但必须（MUST）通过 `Agent Skills Adapter` 接入。

兼容 skill：

- 不得（MUST NOT）写入正式 hub canonical 索引
- 不得（MUST NOT）改变 Kernel primitive
- 应（SHOULD）保守声明 effect class

### MCP Adapter

MCP provider 可以（MAY）通过 `MCP Adapter` 接入统一 operator ABI。

MCP Adapter 必须（MUST）：

- 屏蔽 transport/session 细节
- 把 effect class 映射到 Kernel 可理解的固定枚举
- 保留 policy/evidence/replay 语义

## 错误与重试（Errors/Retry）

以下错误码必须（MUST）稳定保留：

- `E_HITL_REQUIRED`
- `E_CREATOR_SKILL_INVALID`
- `E_CREATOR_SKILL_EXISTS`
- `E_CREATOR_REGISTRY_INVALID`

边界条件（MUST）：

- local unsigned skill 未获批准时必须（MUST）返回 `E_HITL_REQUIRED`
- remember-by-fingerprint 命中旧 fingerprint 时不得（MUST NOT）视为新内容已获批准
- compat skill / MCP skill 未声明为 `read_only` 时，不得（MUST NOT）自动按只读 supersede

## 安全与隐私（Security/Privacy）

- 本地 unsigned skill 的永久批准不得（MUST NOT）绑定裸路径；必须（MUST）绑定 fingerprint。
- compat adapter 必须（MUST）服从现有 policy gate、capability gate 与 evidence 记录。
- `skill-creator` 写本地 skill 时必须（MUST）要求 `fs_write` 能力。

## 可观测性（Observability）

系统必须（MUST）可审计：

- local unsigned skill 的 fingerprint
- approval mode 与 approval event
- `skill_layer`
- `registry_eligible`
- compat adapter 的 operator 映射

## 兼容与版本（Compatibility/Versioning）

- 正式 hub 的 `registry://`、ASVP、policy/evidence 语义不得（MUST NOT）回退。
- 本地 unsigned layer 为 additive change；现有正式 skill 路径必须（MUST）保持兼容。
- 外部 compat skill 与 MCP 接入必须（MUST）是 runtime-only compatibility，不得（MUST NOT）改写 hub canonical model。

## 测试与验收（Tests/Acceptance）

必须（MUST）覆盖：

1. `builtin://creator.write_local_skill` 产物落在 `.agentos/local_skills`
2. 产物包含 `skill_layer=local_unsigned` 与 `registry_eligible=false`
3. remember-by-fingerprint 在内容变化后失效
4. `skill_exec` 且无 operator 声明时默认 `effect_class=external_effect`

验收命令（MUST）：

- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread047_runtime_capabilities_and_web.TestThread047RuntimeCapabilitiesAndWeb.test_builtin_creator_write_local_skill_uses_local_unsigned_layer -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread055_kernel_execution_lane_and_local_skill.TestThread055KernelExecutionLaneAndLocalSkill.test_local_skill_approval_memory_is_bound_to_fingerprint -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread055_kernel_execution_lane_and_local_skill.TestThread055KernelExecutionLaneAndLocalSkill.test_task_service_defaults_skill_exec_without_operator_to_external_effect -v`
