# 技能合同（Skill Contract）

## 目的（Purpose）

定义技能的“可验证执行合同”（verifiable execution contract）：输入/输出 schema、执行目标（local/remote）、安全声明（egress、secrets）、测试与 acceptance rules。

## 范围（Scope）

涵盖：
- 合同字段
- 执行目标声明
- compile artifacts 与 runtime enforcement 的边界

## 核心概念（Concepts）

见 `docs/glossary.md`：技能合同（Skill Contract）、沙箱（Sandbox）、混合执行（Hybrid Execution）。

## 接口/数据结构（Interfaces/Data）

技能合同必须（MUST）声明：
- `inputs_schema`、`outputs_schema`
- `execution_targets`：`local|remote|auto`（或更细分）
- `data_requirements`：数据驻留/敏感等级
- `network_egress`：允许的域名/协议（或默认禁止）
- `requires_secrets`：是否需要 secrets broker
- `risk_level`：用于路由与审批
- `tests` 与 `acceptance_rules`

## 语义与状态机（Semantics/State Machine）

- 合同声明用于路由与治理；实际执行时必须由 PEP 强制（见 `POLICY_DELEGATION.md`）。

## 错误与重试（Errors/Retry）

- 合同不满足（例如执行目标不支持）必须返回明确错误码。

## 安全与隐私（Security/Privacy）

- 本地第三方执行默认 WASM/WASI（见 ADR-0004）。
- 第三方默认云端沙箱（见 ADR-0005）。

## 可观测性（Observability）

- 每次执行需记录合同版本与执行目标。

## 兼容与版本（Compatibility/Versioning）

见 `VERSIONING_COMPAT.md`。

## 测试与验收（Tests/Acceptance）

- 合同字段缺失必须在编译期或加载期失败。

