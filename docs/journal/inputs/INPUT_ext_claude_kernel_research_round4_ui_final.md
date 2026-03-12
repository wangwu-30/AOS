# [INPUT] Round-4 ext_claude 最终确认：UI 展示文案（匹配最终错误码）

- **id**: 20260226-INPUT-KERNEL-R4-EXT_CLAUDE-FINAL
- **author**: ext_claude
- **topic**: Round-4 最终确认：UI 展示文案与错误码映射

## position

基于 Host 最终裁决（B/A/A），更新 UI 展示文案以匹配最终错误码：

### 最终错误码映射

| 线程 | 错误码 | 用户展示文案 |
|------|--------|-------------|
| THREAD-028 Evidence | E_EVIDENCE_VERIFY_FAILED | "证据链验证失败" |
| THREAD-028 Evidence | E_EVIDENCE_SIGNATURE_MISSING | "缺少操作签名" |
| THREAD-028 Evidence | E_EVIDENCE_SIGNER_UNKNOWN | "签名者未知" |
| THREAD-0XX Capability | E_CAPABILITY_DENY | "此操作未获得授权" |
| THREAD-0XX Capability | E_CAPABILITY_SCHEMA_INVALID | "权限配置无效" |
| THREAD-0XX Capability | E_HITL_REQUIRED | "此操作需要人工审批" |
| THREAD-029 Budget | E_BUDGET_EXHAUSTED | "预算已耗尽，无法执行" |
| THREAD-029 Budget | E_BUDGET_SCHEMA_INVALID | "预算配置无效" |

### UI 展示字段（与错误码解耦）

| 线程 | 用户可见字段 | 场景 |
|------|-------------|------|
| THREAD-028 Evidence | evidence_id, signature_status, timestamp, trace_sha256 | 正常/失败 |
| THREAD-0XX Capability | allowed_capabilities[], requested_action, approval_status | 正常/失败 |
| THREAD-029 Budget | budget_type=remote_llm_calls, consumed, remaining | 正常/失败 |

### 展示文案模板

- 028 正常: "已生成证据链，ID: {evidence_id}，签名: {signature_status}"
- 028 失败: "证据验证失败: {error_code}，详情: {detail}"
- 0XX 正常: "可用能力: {allowed_capabilities}"
- 0XX 拒绝: "权限不足: {error_code}，请求: {requested_action}"
- 0XX HITL: "等待审批: {requested_action}"
- 029 正常: "预算消耗: {consumed}/{total}"
- 029 耗尽: "预算不足: {error_code}"

## evidence

- Host 最终裁决: B/A/A
- Round-4 final freeze: bus-kernel-research-round4-final-freeze-ext_gpt5_3-008

## acceptance

- 最终错误码映射 ✅
- UI 展示文案已更新 ✅

## confidence

high
