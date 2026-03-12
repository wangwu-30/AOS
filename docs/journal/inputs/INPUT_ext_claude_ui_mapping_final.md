# [INPUT] 最终 UI 展示映射（THREAD-028/029/030）

- **id**: 20260227-UI-MAPPING-FINAL
- **author**: ext_claude (acting as host)
- **topic**: 最终 UI 展示文案映射（匹配所有冻结决策）

## 最终线程编号

| 线程 | THREAD-ID | 主题 |
|------|-----------|------|
| Evidence Integrity | THREAD-028 | 证据链签名与验证 |
| Capability Schema | THREAD-030 | 权限控制 |
| Budget v1 | THREAD-029 | 预算控制 |

## 错误码映射（完整）

| THREAD-ID | 错误码 | 用户展示文案 |
|-----------|--------|-------------|
| THREAD-028 | E_EVIDENCE_VERIFY_FAILED | "证据链验证失败" |
| THREAD-028 | E_EVIDENCE_SIGNATURE_MISSING | "缺少操作签名" |
| THREAD-028 | E_EVIDENCE_SIGNER_UNKNOWN | "签名者未知" |
| THREAD-030 | E_CAPABILITY_DENY | "此操作未获得授权" |
| THREAD-030 | E_CAPABILITY_SCHEMA_INVALID | "权限配置无效" |
| THREAD-030 | E_HITL_REQUIRED | "此操作需要人工审批" |
| THREAD-029 | E_BUDGET_EXHAUSTED | "预算已耗尽，无法执行" |
| THREAD-029 | E_BUDGET_SCHEMA_INVALID | "预算配置无效" |

## UI 展示字段

| 线程 | 用户可见字段 | 场景 |
|------|-------------|------|
| THREAD-028 | evidence_id, signature_status, timestamp, trace_sha256 | 正常/失败 |
| THREAD-030 | allowed_capabilities[], requested_action, approval_status | 正常/失败 |
| THREAD-029 | budget_type=remote_llm_calls, consumed, remaining | 正常/失败 |

## 展示文案模板

### THREAD-028 Evidence
- 正常: "已生成证据链，ID: {evidence_id}，签名: {signature_status}"
- 失败: "证据验证失败: {error_code}，详情: {detail}"

### THREAD-030 Capability
- 正常: "可用能力: {allowed_capabilities}"
- 拒绝: "权限不足: {error_code}，请求: {requested_action}"
- HITL: "等待审批: {requested_action}"

### THREAD-029 Budget
- 正常: "预算消耗: {consumed}/{total}"
- 耗尽: "预算不足: {error_code}"

## evidence

- Host 最终裁决: B/A/A
- 实现阶段确认: bus-impl-phase-host-confirm-001
- 0XX 正式编号: THREAD-030

## acceptance

- 线程编号确认 ✅
- 错误码完整映射 ✅
- UI 展示字段确认 ✅

## confidence

high
