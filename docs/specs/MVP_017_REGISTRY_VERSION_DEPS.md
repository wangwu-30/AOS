# MVP-017 Registry 版本与依赖（Registry Versioning & Dependencies, local-only）

- 状态（Status）：Draft
- 日期（Date）：2026-02-20
- 目标 Spike（Target Spike）：REG2
- 相关规范（Related Specs）：
  - `docs/specs/MVP_013_REGISTRY.md`（REG1 content addressing）
  - `docs/specs/SKILL_PACKAGE_ASVP.md`（ASVP 包形态）
  - `docs/specs/EVIDENCE_TRACE.md`（resolution evidence）
  - `docs/specs/VERSIONING_COMPAT.md`（versioning strategy）

## 1. 目的（Purpose）

在 REG1 的基础上，为本地 Skill Registry 引入最小化的：

- 版本（versioning）：按 `name` + `version` 组织多版本条目
- 依赖（dependencies）：entry 可声明依赖项，并支持确定性解析依赖图（dependency graph）

前提：MVP 阶段仍为 local-only，不引入网络下载。

## 2. 核心原则（Principles）

1. 不破坏 REG1：`registry://<registry_id>` 仍是唯一可执行引用（execution ref）。
2. Query ref 新增不替换：`registryq://...` 仅用于解析（resolve），不能直接执行。
3. Deterministic：相同 index 内容 -> 相同解析结果（不依赖 wall-clock）。
4. Fail-Closed：缺包/歧义/循环 -> reject + evidence。
5. Evidence by default：解析动作必须写 `kind=routing` evidence，便于回放与仲裁。

## 3. 引用形态（Skill Ref Forms）

- Execution ref（可执行）：
  - `registry://<registry_id>`
- Query ref（解析用）：
  - `registryq://<name>@<constraint>`

### 3.1 constraint 子集（MVP）

- `*`：选择最高版本（highest version）
- `1.2.3`：精确版本匹配（exact）

> 版本排序：MVP 采用 semver `major.minor.patch` 三段整数，按 (major,minor,patch) 比较。

## 4. Index 扩展（Local Index Extension）

在 `data/registry/index.json` 的 entry 里新增字段（可选）：

- `name`: string（来自包内 `contract.skill`）
- `version`: string（来自包内 `contract.skill`）
- `deps`: array[string]（每项为 `registryq://...`）

## 5. 解析算法（Resolution）

### 5.1 resolve(query_ref) -> registry_id

输入：`registryq://name@constraint`

输出：单一 `registry_id`，规则：

- 若 constraint 为精确版本：
  - 选择 `name` 与 `version` 完全匹配的唯一条目；多条 -> ambiguous -> fail-closed
- 若 constraint 为 `*`：
  - 在 `name` 匹配集合里选择 semver 最高版本；同版本多条 -> ambiguous -> fail-closed

### 5.2 resolve_deps(root_registry_id) -> graph

对 entry.deps 做 BFS/DFS：

- 缺包/歧义 -> fail-closed
- 检测循环（cycle）-> fail-closed

## 6. CLI（接口）

- `mvp registry-resolve --ref registryq://... [--data-dir data] [--with-deps]`
  - 输出：解析结果（registry_id/skill_ref）与 evidence_refs

## 7. Acceptance（验收）

- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_reg2_registry_version_deps.py' -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`

