# SYNTHESIS: THREAD-028 Evidence Integrity v1（Signed Turn Manifest）

- `thread_id`: `20260226-EVIDENCE-INTEGRITY-028`
- `updated_at`: `2026-02-26`
- `status`: `resolved`

## 综合结论

- 采用 additive 的 per-turn signed manifest 方案，不修改现有 EvidenceRef/TraceEvent schema。
- “turn” 作为签名单位：同一 `trace_id/turn_id` 只允许 1 份 manifest（重复生成 fail-closed）。
- `trace_sha256` 采用 per-turn slice hash：读取 `data/traces/<trace_id>.jsonl` 原始行 bytes，筛选 `ctx.turn_id==<turn_id>`，按文件顺序拼接后做 sha256。
- verify 工具与 perf_bench 工具均为稳定 JSON + 稳定 exit code，便于 admission/CI 门禁。

## 关键实现要点（P0）

- manifest 落盘路径（冻结）：
  - `data/evidence/manifests/<trace_id>/<turn_id>.json`
  - `data/evidence/manifests/<trace_id>/<turn_id>.json.sig`
- `.sig` 格式（冻结）：
  - Ed25519 raw signature，base64 单行文本，末尾 `\\n`
- Seal 时机：
  - 通过 `Orchestrator.finalize_turn_manifest(...)` 显式 finalize（避免多 span 多次执行导致冲突）
- 篡改检测：
  - 同时校验 evidence meta 的 sha256 与实际 blob 的 sha256（blob tamper -> verify fail-closed）

## Gate（通过条件）

1. 不新增 ExecuteRequest 顶层字段（policy_context-only）
2. fail-closed / replay-mode 约束不降级
3. manifest 重复生成必须 `E_EVIDENCE_SIGNATURE_EXISTS`
4. tamper detection false-negative = 0（测试覆盖）
5. 全量回归全绿

## 验收锚点

- `tests/test_thread028_evidence_integrity.py`
- `src/agentos_next/tools/verify_evidence.py`
- `src/agentos_next/tools/perf_bench.py`
- `docs/specs/MVP_028_EVIDENCE_INTEGRITY.md`

