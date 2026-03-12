# SYNTHESIS: REG2 Registry Versioning & Dependencies (local-only)

- `thread_id`: `20260220-REG2-VDEPS-013`
- `updated_at`: `2026-02-20`
- `status`: `accepted`
- `owner`: `human + codex`

## Summary（综合摘要）

结论：以“新增 query ref（registryq://）+ 本地 index 元数据扩展 + deterministic 解析 evidence”的最小增量实现 REG2，同时不破坏 REG1 的 `registry://<registry_id>` 执行语义。

关键共识：

- `registry://` 继续只表示内容寻址 id（content-addressed id），用于执行与回放。
- `registryq://` 表示查询式引用（query ref），只用于解析（resolve），不能直接执行；必须先 resolve 成 `registry://...`。
- 约束子集（constraint subset）：MVP 仅支持 `*`（最高版本）与精确版本（`1.2.3`），并采用确定性的 semver 排序。
- 解析过程必须写 `kind=routing` evidence，记录候选集合与选择结果；缺包/歧义/循环必须 fail-closed。

## Evidence（证据）

- `docs/specs/MVP_017_REGISTRY_VERSION_DEPS.md`
- `src/agentos_next/kernel/skill_registry.py`
- `src/agentos_next/cli.py`
- `tests/test_spike_reg2_registry_version_deps.py`
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`（全量回归）

