# DECISIONS: REG2 Registry Versioning & Dependencies (local-only)

- `thread_id`: `20260220-REG2-VDEPS-013`
- `updated_at`: `2026-02-20`
- `status`: `accepted`

## Decision 001: 引入 registryq:// 查询式 skill_ref（不破坏 registry:// 执行语义）

- **状态**: `accepted`
- **结论**:
  - 保持 `registry://<registry_id>` 作为唯一可执行引用（execution ref）。
  - 新增 `registryq://<name>@<constraint>` 作为解析引用（query ref），必须 resolve 为 `registry://...` 后才能执行。
  - constraint MVP 子集：`*`（最高版本）与精确版本 `1.2.3`。

## Decision 002: 解析过程 evidence by default + fail-closed

- **状态**: `accepted`
- **结论**:
  - `registry-resolve` 解析必须写 `kind=routing` evidence：
    - 输入 ref
    - 候选集合（candidate ids + versions）
    - 选择结果（selected）
  - 缺包/歧义/循环必须拒绝（fail-closed），不做隐式回退。

## Gate（必须通过的门禁）

1. 不破坏 REG1：`registry://<registry_id>` 解析与执行语义不变。
2. 不新增 ExecuteRequest 顶层字段；扩展点仅在 registry 的本地解析机制。
3. deterministic：相同 index 内容必须得到相同解析结果。
4. fail-closed：missing/ambiguous/cycle -> reject + evidence。

## Acceptance（可验证验收）

- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_spike_reg2_registry_version_deps.py' -v`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`

## Evidence（证据）

- `docs/specs/MVP_017_REGISTRY_VERSION_DEPS.md`
- `src/agentos_next/kernel/skill_registry.py`
- `src/agentos_next/cli.py`
- `tests/test_spike_reg2_registry_version_deps.py`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

