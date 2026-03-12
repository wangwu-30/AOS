# 版本与兼容性（Versioning & Compatibility）

## 目的（Purpose）

定义对外协议、spec、evidence/trace schema 的版本化策略。

注意：本项目当前处于 Demo 阶段，默认不承诺向后兼容（Backward Compatibility）。但仍要求所有持久化对象携带版本字段，以便后续进入稳定阶段时可演进。

## 范围（Scope）

涵盖：
- Spec 版本
- evidence/trace schema 版本与迁移
- 接口字段的弃用（deprecation）策略

## 核心概念（Concepts）

见 `docs/glossary.md`：兼容（Compatibility）、回放（Replay）。

## 接口/数据结构（Interfaces/Data）

- 所有可持久化对象（Evidence/Trace/Artifact）必须（MUST）包含 `schema_version`。

## 语义与状态机（Semantics/State Machine）

- Demo 阶段允许（MAY）破坏性变更。
- 进入稳定阶段后（状态由 ADR 宣布），任何破坏性变更必须（MUST）：
  - 增加 major 版本
  - 提供迁移说明
  - 更新相关 ADR

## 错误与重试（Errors/Retry）

- 版本不兼容必须返回明确错误，并建议升级路径。

## 安全与隐私（Security/Privacy）

- 迁移过程中不得引入明文泄漏；端侧加密同步必须保持兼容。

## 可观测性（Observability）

- 必须能统计不同 schema_version 的占比与迁移失败率。

## 测试与验收（Tests/Acceptance）

- Demo 阶段：至少保证当前版本的 evidence/trace 可回放。
- 稳定阶段：旧版 evidence 在新版内核中必须可回放（允许降级呈现，但不能 silent break）。
