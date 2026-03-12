# DECISIONS: P1 Skill Registry (SR1) Spike Definition

- `thread_id`: `20260219-SR1-SKILL-REGISTRY-008`
- `updated_at`: `2026-02-19`
- `status`: `draft`

## Decision 001: Minimal Registry Index Data Model

- **状态**: `proposed`
- **结论**: SR1 采用单文件索引（single-file index）`registry_index.json`，最小 entry 字段为 `name/version/skill_ref/compiled_artifacts_sha256`。
- **理由**:
  - 最小闭环支持解析（resolve）与完整性校验（integrity）。
  - 与现有 `skill_creator` 的“目录扫描发现”可并存，不阻断 CR1。

## Decision 002: SemVer Minimal Subset + Selector Grammar

- **状态**: `proposed`
- **结论**: SR1 仅支持三段 SemVer（`MAJOR.MINOR.PATCH`，整数），selector 仅支持 `vMAJOR[.MINOR[.PATCH]]`。
- **选择策略**:
  - `vMAJOR` 选择该 major 下最大版本
  - `vMAJOR.MINOR` 选择该 minor 下最大 patch
  - `vMAJOR.MINOR.PATCH` 精确匹配
- **理由**:
  - 兼容现有 `registry://.../v1` 形式（见 `tests/test_remote_executor_cr1_payload.py` 的示例引用）。
  - 避免引入复杂 range spec（`^`、`~`、`>=`）与 pre-release 语义。

## Decision 003: Compiled Artifacts Hash Definition

- **状态**: `proposed`
- **结论**: `compiled_artifacts_sha256` 定义为必需 compiled 文件集合的确定性集合指纹（set fingerprint），不纳入 mtime 等非确定性元信息。
- **必需文件集合**:
  - `compiled/intent_snapshot.json`
  - `compiled/prompt_bundle.json`
  - `compiled/execution_ir.json`
- **理由**:
  - 与 CR1 的最小编译产物集合一致（`docs/specs/SKILL_CREATOR.md`）。
  - 可作为回放稳定性与缓存 key 的基础。

## Decision 004: Dependency Resolution Policy (SR1 no-deps)

- **状态**: `proposed`
- **结论**: SR1 不做依赖解析（dependency resolution），registry entry 不包含 deps（或必须为空）。
- **理由**:
  - 降低首次落地复杂度，避免引入图算法与冲突解算。
  - 依赖能力可在 SR2 通过显式 `deps` 字段与 lockfile 机制引入。

## Decision 005: Acceptance Tests & Commands

- **状态**: `proposed`
- **结论**: SR1 以“解析正确性 + 稳定错误码 + hash 校验”为准入门槛（admission gate）。
- **必须覆盖的用例（MUST）**:
  - selector 解析：合法与非法（稳定错误码）
  - 版本选择：`vMAJOR`、`vMAJOR.MINOR`、精确匹配
  - 索引校验：缺字段、重复条目
  - hash mismatch：返回 `E_REGISTRY_HASH_MISMATCH`
- **建议命令（proposal）**:
  - `python3 -m agentos_next.cli mvp registry-index --registry-root <dir> --out <dir>/registry_index.json`
  - `python3 -m agentos_next.cli mvp registry-resolve --registry-index <dir>/registry_index.json --skill-ref registry://<name>/v1`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

