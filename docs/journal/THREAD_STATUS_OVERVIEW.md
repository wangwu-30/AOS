# THREAD 状态总览

## Kernel Research + Implementation 状态

### 已 ACCEPTED

| THREAD-ID | 主题 | 状态 | Gate 状态 |
|-----------|------|------|----------|
| THREAD-028 | Evidence Integrity v1 | ACCEPTED | 124/124 + gate ok |
| THREAD-029 | Budget v1 | ACCEPTED | 124/124 + gate ok |
| THREAD-030 | Capability Schema v1 | ACCEPTED | 124/124 + gate ok |
| THREAD-032 | Context Compiler | ACCEPTED | 124/124 + gate ok |
| THREAD-033 | PA-EV1（EventEnvelope/EventLog/Outbox/Dedup） | ACCEPTED | 134/134 + gate ok |
| THREAD-034 | PA-CH1（Telegram Connector） | ACCEPTED | 129/129 + gate ok |
| THREAD-035 | PA-MTR0（Metering Evidence v0） | ACCEPTED | 134/134 + gate ok |
| THREAD-036 | PA-E2E（033+034+035） | ACCEPTED | 137/137 + gate ok |
| THREAD-040 | PA-DEMO（Visible Roundtrip） | ACCEPTED | 140/140 + gate ok |
| THREAD-041 | PA-WEBHOOK-SERVER（Loopback Ingress Service） | ACCEPTED | 158/158 + gate ok |
| THREAD-042 | PA-TG1（TaskGraph） | ACCEPTED | 153/153 + gate ok |
| THREAD-043 | PA-MEM1（Progressive Context Pipeline） | ACCEPTED | 157/157 + gate ok |
| THREAD-044 | PA-POLLING（Local Polling Mode） | ACCEPTED | 162/162 + gate ok |

---

## 冻结决策汇总

### THREAD-028 Evidence Integrity v1
- manifest 路径: `data/evidence/manifests/<trace_id>/<turn_id>.json`
- 签名路径: `data/evidence/manifests/<trace_id>/<turn_id>.json.sig`
- trace_sha256: per-turn slice hash
- 错误码:
  - E_EVIDENCE_VERIFY_FAILED
  - E_EVIDENCE_SIGNATURE_MISSING
  - E_EVIDENCE_SIGNER_UNKNOWN
  - E_EVIDENCE_SIGNATURE_EXISTS
- 性能阈值: p95 增幅 ≤15%

### THREAD-030 Capability Schema v1
- policy_context.capabilities[] + PEP default deny
- 错误码:
  - E_CAPABILITY_DENY
  - E_CAPABILITY_SCHEMA_INVALID
  - E_HITL_REQUIRED (复用)

### THREAD-029 Budget v1
- budget_slice = remote_llm_calls
- allow-check ≤2ms/req
- (N+1) 拦截率 = 100%
- 错误码:
  - E_BUDGET_EXHAUSTED
  - E_BUDGET_SCHEMA_INVALID

### THREAD-032 Context Compiler
- C0~C4 分层：Identity Core / Capability Index / Memory Index / Runtime Snapshot / Step Context
- 预算单位：bytes
- Goldilocks: 40%-70%
- 错误码:
  - E_CTX_SCHEMA_INVALID
  - E_CTX_BUDGET_EXCEEDED
  - E_CTX_POLICY_VIOLATION
  - E_CTX_REPLAY_DENY
- Violation Codes:
  - identity_mutation_attempt
  - cross_workspace_leakage
  - budget_trim_overflow
  - append_only_violation

---

## Non-negotiables (所有线程共用)

- top_level_api_stable
- fail_closed
- replay_mode_no_side_effects

---

## Gate 验收命令

```bash
# 单元测试
PYTHONPATH=src python3 -m unittest discover -s tests -v

# Thread Gate
PYTHONPATH=src python3 -m agentos_next.tools.thread_gate_check

# Performance Bench
PYTHONPATH=src python3 -m agentos_next.tools.perf_bench --op sign --count 1000
PYTHONPATH=src python3 -m agentos_next.tools.perf_bench --op verify --count 1000
PYTHONPATH=src python3 -m agentos_next.tools.perf_bench --op budget --count 1000
```

---

*Updated: 2026-02-28*
