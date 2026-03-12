# MVP-013 技能注册表（Skill Registry）与内容寻址（Content Addressing）

- 状态（Status）：Draft
- 日期（Date）：2026-02-19
- 目标 Spike（Target Spike）：Spike-REG1
- 相关规范（Related Specs）：
  - `docs/specs/SKILL_PACKAGE_ASVP.md`（ASVP manifest + canonical JSON）
  - `docs/specs/EXECUTOR_API.md`（ExecuteRequest/ExecuteResult）
  - `docs/specs/EVIDENCE_TRACE.md`（Evidence/Trace）
  - `docs/specs/VERSIONING_COMPAT.md`（Versioning）

## 1. 目的（Purpose）

定义一个最小 Skill Registry（技能注册表，Skill Registry）机制，使 `ExecuteRequest.skill_ref` 支持从“路径”（path）演进到“引用”（ref）：

- `registry://<registry_id>`

其中 `<registry_id>` 是对 ASVP `manifest.json` 的规范化内容（canonical bytes）做哈希得到的内容寻址 ID（content-addressed id）。

MVP 约束：
- registry 仅本地（local-only），不引入网络下载
- registry 是只读映射（read-only mapping）：`registry_id -> local_path`
- 执行时必须保持 ASVP 验签语义不变（verify-asvp 仍有效）

## 2. 核心原则（Principles）

1. 可复现（Deterministic）：相同 skill 包内容必须生成相同 `registry_id`，用于 replay/仲裁。
2. Fail-Closed：registry 解析失败、找不到映射、映射不一致时必须拒绝执行并写 evidence/trace。
3. 不改变包验证：ASVP verify 的输入仍是“skill_dir 目录”，registry 只负责解析到目录路径。
4. 不引入网络：任何缺包/缺映射不触发下载逻辑。

## 3. 不可破坏约束（Non-Negotiables / Invariants）

- 不得破坏既有 CLI 稳定 JSON 输出与 evidence/trace schema。
- 不得在 registry 解析阶段引入任何远程调用。
- registry id 必须与 ASVP canonical 规则一致（避免签名/哈希口径分叉）。

## 4. registry_id 定义（Content Address）

### 4.1 Canonical Manifest Bytes

使用 `manifest.json` 的 canonical bytes（规范化 JSON）作为哈希输入：
- key 按字典序排序
- separators 无空格（`,` 与 `:`）
- UTF-8 编码

此 canonical 规则必须与 ASVP 签名时的 canonical 规则一致（参见 `docs/specs/SKILL_PACKAGE_ASVP.md`）。

### 4.2 registry_id 算法

MVP 建议：
- `registry_id = "rg_" + sha256(canonical_manifest_bytes)[:20]`
- skill_ref 形式：`registry://rg_<hex20>`

> 注：截断长度是工程权衡（tradeoff），若未来需要更低碰撞概率可扩展为更长；必须走版本化策略（VERSIONING_COMPAT）。

## 5. 本地索引（Local Index）

### 5.1 落盘位置（Persistence）

建议（SHOULD）：
- `data/registry/index.json`

形状：
```json
{
  "schema_version": "1.0.0",
  "entries": {
    "rg_...": {
      "skill_dir": "/abs/path/to/skill_dir",
      "manifest_sha256": "full_sha256_hex",
      "signer_id": "string (from manifest.json)"
    }
  }
}
```

约束：
- 索引是只读映射：执行时不得隐式修改 skill 包内容。
- 如果映射指向的目录内容与 manifest 校验不一致，必须 fail-closed（等效 ASVP verify 失败）。

### 5.2 注册（Register）

MVP 允许一个显式的“注册动作”（register action），但不强制一定有新 CLI；实现可以通过：
- library API：`SkillRegistry.register(skill_dir) -> registry_id`
- 或 CLI：`mvp registry-add --skill-dir ...`（如果新增）

注册必须（MUST）写 evidence（kind=snapshot 或 routing），用于回放“为什么这个 registry id 指向这个路径”。

## 6. 执行语义（Execution Semantics）

当 `ExecuteRequest.skill_ref` 以 `registry://` 开头时：
1. 执行入口必须解析 registry id
2. 查找本地 index 得到 `skill_dir`
3. 将 skill_dir 作为真实加载路径交给现有 package loader（ASVP verify 不变）
4. 记录 evidence：
   - resolution evidence：`registry_id -> skill_dir`（kind=routing 或 snapshot）
   - 后续执行 evidence/trace 与 path 模式等价

语义要求：
- 使用 `registry://` 与直接使用 `skill_dir` 路径执行必须（MUST）在“执行结果语义”上等效（不要求 evidence ref 完全相同，但要求 status/error_code/output contract 一致）。

## 7. 错误码（Error Codes）

建议复用：
- registry 解析失败：`E_INPUT_SCHEMA`
- registry 未找到：`E_EXECUTION_FAILED`（或新增 `E_REGISTRY_NOT_FOUND`，但新增必须锁测试并写入版本策略）
- ASVP 验签失败：沿用现有 ASVP failure 语义（由 loader 抛错并映射为稳定错误码）

## 8. Acceptance（验收）

必须（MUST）：
- 全量回归：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
- 新增测试覆盖（示例要求）：
  1. 对示例 skill 包（`examples/skills/personal_assistant_brief`）计算 `registry_id`
  2. 建立本地 index 映射 `registry_id -> path`
  3. 用 `mvp exec --skill-ref registry://...`（或等价 API）执行
  4. 断言：
     - 与路径执行的 status/error_code/output contract 等效
     - verify-asvp 打开时仍可验签通过
     - resolution evidence/trace 可追溯

