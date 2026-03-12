# 2026-02-20 外部专家协作线程 013 (External Expert Collaboration Thread 013)

- `thread_id`: `20260220-REG2-VDEPS-013`
- `status`: `round_4_completed`
- `updated_at`: `2026-02-20`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

立项 REG2：在 REG1（`registry://<registry_id>` 内容寻址，content addressing）基础上，引入最小“版本（versioning）与依赖（dependencies）”能力，使本地 registry 能支持：

- 通过 **查询式 skill_ref（query ref）** 解析到确定的 `registry_id`（deterministic resolution）
- 解析过程可审计、可回放（resolution evidence + trace）
- 依赖图解析 fail-closed（missing/ambiguous/cycle -> reject）

## 范围 (In Scope)

- 新增 query ref 形态（不破坏现有 `registry://<registry_id>` 语义）：
  - `registryq://<name>@<constraint>`
  - 约束（constraint）MVP 子集：`*`（最高版本），或精确版本 `1.2.3`
- 扩展本地 registry index（local-only）元数据：
  - entry 增加 `name`、`version`（来自包内 `contract.skill`）
  - entry 可选 `deps`（列表，元素为 `registryq://...`）
- 提供解析 API 与 CLI：
  - `mvp registry-resolve --ref registryq://...` -> 输出 `registry://<registry_id>`
  - 可选：`--with-deps` 输出解析后的依赖图（graph）
- 证据与回放：
  - 解析动作必须写 evidence（kind=routing），记录候选集合与选择结果。

## 非范围 (Out of Scope)

- 网络下载、远程 registry、marketplace
- 复杂 semver 约束（范围、^、~、预发布）与依赖冲突自动修复
- 依赖安装/更新策略（仅解析，不自动下载）

## 非协商约束 (Non-Negotiables)

- 不改变 ExecuteRequest 顶层字段（top-level API stable）；不引入 schema-breaking 变更。
- fail-closed 不降级：解析不确定/冲突/缺包必须拒绝并记录 evidence。
- 解析必须 deterministic：相同 index 内容必须得到相同解析结果与 evidence（除 ts）。

## 轮次进度 (Rounds)

- Round 0 (线程设定): 完成
- Round 1 (独立提案): 完成（见 inputs）
- Round 2 (交叉评审): N/A（MVP 快速迭代：先落地再补交叉评审）
- Round 3 (综合): 完成（见 synthesis）
- Round 4 (裁决): 完成（见 decisions）

## Evidence (Links)

- `docs/specs/EXPERT_COLLAB_PROTOCOL.md`
- `docs/specs/MVP_013_REGISTRY.md`（REG1）
- `docs/specs/MVP_017_REGISTRY_VERSION_DEPS.md`（REG2 规范）
- `src/agentos_next/kernel/skill_registry.py`
- `src/agentos_next/cli.py`
- `tests/test_spike_reg2_registry_version_deps.py`
- `docs/journal/SYNTHESIS_20260220-REG2-VDEPS-013.md`
- `docs/journal/DECISIONS_20260220-REG2-VDEPS-013.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260220_REG2_VDEPS_013_round2_cross_review.md`

