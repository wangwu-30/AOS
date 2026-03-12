# 2026-02-26 外部专家协作线程 028 (External Expert Collaboration Thread 028)

- `thread_id`: `20260226-EVIDENCE-INTEGRITY-028`
- `status`: `round_3_completed`
- `updated_at`: `2026-02-26`
- `owner`: `human + codex`

## 问题陈述 (Problem Statement)

为 AgentOS 内核提供证据链完整性（Evidence Integrity）基础：对每个 turn 的 evidence + trace slice 生成可验证的签名 manifest，确保篡改可检测（tamper-evident）与审计可回放。

## 范围 (In Scope)

- per-turn signed manifest：
  - `data/evidence/manifests/<trace_id>/<turn_id>.json`
  - `data/evidence/manifests/<trace_id>/<turn_id>.json.sig`
- `trace_sha256` 冻结为 per-turn slice hash（按原始 JSONL 行 bytes）
- verify 工具：稳定 JSON + 稳定 exit code（0/2/3）
- perf_bench 工具：sign/verify/budget（budget 仅 baseline）
- 重复生成 fail-closed：`E_EVIDENCE_SIGNATURE_EXISTS`

## 非范围 (Out of Scope)

- HSM/TPM/安全硬件密钥托管
- Remote Executor 端到端签名透传（P1）
- TURN_FINISHED 自动 finalize（P1，需避免多 span 冲突）

## 非协商约束 (Non-Negotiables)

- top-level API stable（不新增 ExecuteRequest 顶层字段；扩展仅 policy_context）
- fail-closed 不降级
- replay-mode 无新增副作用（sign/verify 路径必须遵守）

## 轮次进度 (Rounds)

- Round 0: 已完成（冻结路径/阈值/重复生成语义）
- Round 1: 已完成（实现方案与验收）
- Round 2: 已完成（cross-review marker + admission MUST）
- Round 3: 已完成（实现 + tests + tools）
- Round 4: 待 host 标记 accepted

## Evidence (Links)

- `docs/specs/MVP_028_EVIDENCE_INTEGRITY.md`
- `src/agentos_next/kernel/evidence_manifest.py`
- `src/agentos_next/kernel/orchestrator.py`
- `src/agentos_next/tools/verify_evidence.py`
- `src/agentos_next/tools/perf_bench.py`
- `tests/test_thread028_evidence_integrity.py`
- `docs/journal/inputs/INPUT_thread_20260226_EVIDENCE_INTEGRITY_028_round1.md`

## Round 2 Cross Review (Marker)

- `docs/journal/inputs/INPUT_thread_20260226_EVIDENCE_INTEGRITY_028_round2_cross_review.md`

