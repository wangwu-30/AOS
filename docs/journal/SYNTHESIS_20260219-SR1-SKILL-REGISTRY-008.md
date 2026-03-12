# SYNTHESIS: P1 Skill Registry (SR1) Spike Definition

- `thread_id`: `20260219-SR1-SKILL-REGISTRY-008`
- `updated_at`: `2026-02-19`
- `status`: `draft`
- `owner`: `human + codex`

## Summary（综合摘要）

SR1（Skill Registry v1）以 **本地 registry 快照（local snapshot）** 为中心：提供一个可版本化的索引文件（index）来描述“有哪些技能版本可用，以及它们的执行引用（skill_ref）与编译产物指纹（compiled artifacts hash）”。解析侧把 `registry://<name>/<selector>` 解析为一个具体条目（entry），并输出可用于执行器（Executor）的 `skill_ref`（例如本地路径或 URL）。

SR1 只覆盖版本选择与完整性校验，不解决依赖（no-deps），也不引入网络 registry 服务。

## Minimal Registry Data Model（最小数据模型）

### 1) Registry Index（索引文件）形态

建议新增一个索引文件（示例命名）：`<registry_root>/registry_index.json`，最小结构：

```json
{
  "schema_version": "1.0.0",
  "generated_at": "2026-02-19T00:00:00Z",
  "entries": [
    {
      "name": "personal_assistant_brief",
      "version": "1.2.3",
      "skill_ref": "/abs/path/to/registry/personal_assistant_brief/1.2.3",
      "compiled_artifacts_sha256": "hex_sha256"
    }
  ]
}
```

最小必需字段（MUST）：
- `entries[].name`
- `entries[].version`
- `entries[].skill_ref`
- `entries[].compiled_artifacts_sha256`

兼容/扩展策略（forward-compatible）：
- 索引顶层与 entry 允许增加字段；解析侧必须忽略未知字段。
- 所有可持久化对象建议携带 `schema_version`（见 `docs/specs/VERSIONING_COMPAT.md` 的约束）。

### 2) compiled artifacts hash（编译产物指纹）

SR1 的 `compiled_artifacts_sha256` 定义为对“最小必需 compiled 集合”的确定性哈希（deterministic hash），用于完整性校验与回放稳定性：

- “最小必需 compiled 集合”建议与 CR1 对齐：`compiled/intent_snapshot.json`、`compiled/prompt_bundle.json`、`compiled/execution_ir.json`。
- 建议 hash 算法（MUST deterministic across OS）：
  1. 对每个必需文件取 `sha256(file_bytes)` 得到 `file_sha256`
  2. 以文件相对路径排序后拼接成 canonical 文本：`<relpath>\t<file_sha256>\n`
  3. 对 canonical 文本取 `sha256(utf8_bytes)` 得到 `compiled_artifacts_sha256`

备注：
- 该 hash 是“集合指纹”（set fingerprint），不依赖文件 mtime、inode 等非确定性信息。

## Version Parsing & Selection（版本解析与选择，SemVer 最小子集）

SR1 支持 SemVer 的最小子集（minimal subset）：

- **规范化版本（canonical version）**：`MAJOR.MINOR.PATCH`（三段整数），不支持 pre-release/build metadata。
- **选择器（selector）**：为兼容现有 `registry://.../v1` 写法，selector 采用带 `v` 前缀的 SemVer 前缀形式：
  - `vMAJOR`：选择该 MAJOR 下最高版本（max MINOR/PATCH）
  - `vMAJOR.MINOR`：选择该 MAJOR.MINOR 下最高 PATCH
  - `vMAJOR.MINOR.PATCH`：精确匹配

解析（parse）与排序（order）规则：
- 解析时允许 `version` 字符串前缀 `v`，写入索引时必须规范化为不带 `v` 的 `MAJOR.MINOR.PATCH`。
- 排序按 `(major, minor, patch)` 三元组比较，选择最大者。
- 如果出现同一 `(name, version)` 多条 entry，解析必须 fail-closed（索引无歧义要求）。

建议的 `registry://` 引用格式（proposal）：
- `registry://<name>/<selector>`，例如：
  - `registry://personal_assistant_brief/v1`
  - `registry://personal_assistant_brief/v1.2`
  - `registry://personal_assistant_brief/v1.2.3`

## Dependency Resolution（依赖解析策略：SR1 no-deps）

SR1 明确 no-deps：

- registry entry 不包含依赖字段（deps）；或允许存在 `deps` 但在 SR1 中必须为空列表（MUST `[]`）。
- 解析器（resolver）只解析单个 `skill_ref`，不递归解析其他技能。

## Failure Modes & Stable Error Codes（失败模式与稳定错误码）

建议 SR1 引入稳定错误码（stable error codes），至少包含：

- `E_REGISTRY_INDEX_INVALID`：索引文件缺失/JSON 不合法/字段缺失/重复条目
- `E_REGISTRY_REF_INVALID`：`registry://` 格式非法
- `E_REGISTRY_VERSION_SPEC_INVALID`：selector 不满足 `vMAJOR[.MINOR[.PATCH]]`
- `E_REGISTRY_SKILL_NOT_FOUND`：name 不存在
- `E_REGISTRY_VERSION_NOT_FOUND`：存在 name 但没有匹配版本
- `E_REGISTRY_HASH_MISMATCH`：索引 hash 与实际 compiled artifacts hash 不一致

## Acceptance Tests / Commands（验收测试与命令）

SR1 spike 的验收建议分为 3 组：

1. **版本解析单测（unit tests）**
- 用例：`v1`/`v1.2`/`v1.2.3` 解析与排序选择，非法 selector 返回 `E_REGISTRY_VERSION_SPEC_INVALID`。

2. **索引校验与哈希校验（index + hash validation）**
- 用例：缺字段、重复 `(name, version)`、hash mismatch，分别返回 `E_REGISTRY_INDEX_INVALID` 或 `E_REGISTRY_HASH_MISMATCH`。

3. **端到端解析（E2E resolve）**
- 在临时目录创建一个 registry_root：
  - 写入两版同名技能（例如 `1.0.0`、`1.1.0`）的 compiled artifacts
  - 生成 `registry_index.json`
  - 运行解析命令把 `registry://name/v1` 解析到 `1.1.0`

建议提供的最小命令集合（proposal）：

- `python3 -m agentos_next.cli mvp registry-index --registry-root <dir> --out <dir>/registry_index.json`
- `python3 -m agentos_next.cli mvp registry-resolve --registry-index <dir>/registry_index.json --skill-ref registry://<name>/v1`
- 全量回归：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`

