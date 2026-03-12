# AGENTS.md (Repo Rules)

本仓库默认目标：可开源内核（Kernel）+ 可审计规范（Specs/ADRs），中文为主、关键术语附英文对照。

## 写作规则（必须遵守）

- 术语首次出现使用 `中文（English Term）`，并在 `docs/glossary.md` 收录。
- `docs/specs/` 只写规范性文本：
  - 使用 “必须（MUST）/应该（SHOULD）/可以（MAY）/禁止（MUST NOT）”
  - 必须包含：默认值、错误码、边界条件、兼容策略、测试与验收
  - 禁止包含：讨论过程、聊天式叙述
- `docs/adrs/` 必须记录：
  - 背景、决策、备选方案、取舍、后果、风险与缓解、可观测/验收、关联 Specs
- 任何 PR 若触及接口/语义：必须同时修改至少 1 份 Spec；若改变不可逆设计点必须附 ADR。

