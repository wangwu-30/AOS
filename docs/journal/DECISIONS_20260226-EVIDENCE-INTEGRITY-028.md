# DECISIONS: THREAD-028 Evidence Integrity v1（Signed Turn Manifest）

- `thread_id`: `20260226-EVIDENCE-INTEGRITY-028`
- `updated_at`: `2026-02-26`
- `status`: `proposed_for_acceptance`

## Decision 001: Manifest 形态与落盘路径

- **状态**: `accepted`
- **结论**:
  - per-turn manifest（additive，不改现有 Evidence/Trace schema）
  - 路径冻结：
    - `data/evidence/manifests/<trace_id>/<turn_id>.json`
    - `data/evidence/manifests/<trace_id>/<turn_id>.json.sig`
  - 重复生成语义冻结：fail-closed（不覆盖重签）
    - 错误码：`E_EVIDENCE_SIGNATURE_EXISTS`
    - `reason_code=signature_exists`

## Decision 002: trace_sha256（per-turn slice hash）

- **状态**: `accepted`
- **结论**:
  - `trace_sha256 = sha256(concat(raw_jsonl_line_bytes))`
  - 仅选择 `ctx.turn_id == <turn_id>` 的行，按文件顺序拼接（含 `\\n`）

## Decision 003: 签名格式与验证工具

- **状态**: `accepted`
- **结论**:
  - `.sig` 为 Ed25519 raw signature，base64 单行文本 + 末尾 `\\n`
  - verify 工具输出稳定 JSON + exit code 稳定：
    - 0 = ok
    - 2 = verify_failed
    - 3 = tool_error

## Gate（合并前必须全部满足）

1. 不新增 ExecuteRequest 顶层字段（扩展仅 policy_context）
2. fail-closed / replay-mode 约束不降级
3. tamper detection false-negative = 0
4. perf kill criteria（v1 默认阈值）：
   - sign: p95 增幅 ≤ 15%
   - verify: 1000 events ≤ 2s

## Acceptance

- `PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
- `PYTHONPATH=src python3 -m agentos_next.tools.perf_bench --op sign --count 1000` exit 0
- `PYTHONPATH=src python3 -m agentos_next.tools.perf_bench --op verify --count 1000` exit 0
- 线程三件套存在：
  - `docs/journal/2026-02-26-expert-collab-thread-028.md`
  - `docs/journal/SYNTHESIS_20260226-EVIDENCE-INTEGRITY-028.md`
  - `docs/journal/DECISIONS_20260226-EVIDENCE-INTEGRITY-028.md`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

