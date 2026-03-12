# MVP_028 Evidence Integrity（证据链签名）

目标：为每个 turn 生成可验证的签名 manifest，使 evidence/trace 篡改可检测（tamper-evident），并支持本地/远程审计（audit）。

## Goals（目标）

- per-turn signed manifest（每个 `trace_id/turn_id` 一份）。
- `trace_sha256` 冻结为 per-turn slice hash（可回放、可复验）。
- verify 工具稳定 JSON + 稳定 exit code（用于 admission/CI）。
- fail-closed：缺签名/签名不匹配/篡改均视为验证失败。

## Non-Goals（非目标）

- 硬件密钥托管（HSM/TPM/Secure Enclave）。
- 向量检索、UI 展示等上层能力。
- 自动推断 turn 完成点（v1 采用显式 finalize）。

## Layout（落盘布局）

冻结（frozen）：

- manifest：
  - `data/evidence/manifests/<trace_id>/<turn_id>.json`
- signature：
  - `data/evidence/manifests/<trace_id>/<turn_id>.json.sig`

## Manifest（JSON）

- `schema_version`: `1.0.0`
- `type`: `turn_evidence_manifest`
- `trace_id`, `turn_id`, `workspace_id`
- `operator_ref`, `idempotency_key`
- `execute_status`, `execute_error_code`
- `evidence_refs[]`: `[{ref, kind, sha256, size_bytes}]`
- `trace_sha256`: per-turn slice hash（见下）
- `signer_id`
- `signature_format`: `ed25519_raw_base64`

## Signature（签名格式）

冻结（frozen）：

- `.sig` 内容为 **Ed25519 raw signature** 的 base64 单行文本，末尾必须包含 `\n`。

## trace_sha256（Per-Turn Slice Hash）

冻结（frozen）：

- 读取 `data/traces/<trace_id>.jsonl` 的**原始行 bytes**（包含行尾 `\n`）。
- 仅选择 `ctx.turn_id == <turn_id>` 的行。
- `trace_sha256 = sha256(concat(selected_raw_lines_in_file_order))`。

## Sealing（显式 finalize）

v1 要求由上层在 “turn 已完成” 后显式调用 Kernel finalize：

- `Orchestrator.finalize_turn_manifest(...)`

语义：同一 `trace_id/turn_id` 只能 seal 一次；重复 seal 必须 fail-closed。

## Verification（验证）

verify（`verify_turn_manifest`）必须执行：

1. manifest+sig 文件存在性检查（缺失 -> `E_EVIDENCE_SIGNATURE_MISSING`）
2. `trace_sha256` 复验（不匹配 -> `E_EVIDENCE_VERIFY_FAILED`）
3. evidence 校验：
   - manifest 中每个 `ref` 对应的 `evidence/meta/<ref>.json` 的 `sha256` 必须匹配
   - 对应的 `evidence/blobs/<ref>` 实际内容 hash 必须匹配 meta（否则视为 tampered）
4. 签名验证（失败 -> `E_EVIDENCE_VERIFY_FAILED`）

## Error Codes（错误码冻结）

- `E_EVIDENCE_VERIFY_FAILED`
- `E_EVIDENCE_SIGNATURE_MISSING`
- `E_EVIDENCE_SIGNER_UNKNOWN`
- `E_EVIDENCE_SIGNATURE_EXISTS`（重复生成 fail-closed）

## Tools（工具）

- verify（稳定 JSON / exit code）：
  - `PYTHONPATH=src python3 -m agentos_next.tools.verify_evidence --trace-id <trace_id>`
  - exit code: `0 ok` / `2 verify_failed` / `3 tool_error`
- perf（稳定 JSON / exit code）：
  - `PYTHONPATH=src python3 -m agentos_next.tools.perf_bench --op sign --count 1000`
  - `PYTHONPATH=src python3 -m agentos_next.tools.perf_bench --op verify --count 1000`

## Kill Criteria（量化阈值，v1 默认）

冻结（frozen, v1 default gate）：

- sign: p95 延迟增幅 ≤ 15%（相对未签名基线）
- verify: 1000 events ≤ 2s
- tamper detection：false-negative = 0%

## Replay Semantics（回放语义）

- replay-mode 下不得生成/重签 manifest（zero-write）。
- 若在 replay-mode 调用 finalize：必须 fail-closed（`E_POLICY_DENY` + `reason_code=replay_mode_no_side_effects`）。

## Acceptance（验收）

- `tests/test_thread028_evidence_integrity.py` 全绿
- `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
