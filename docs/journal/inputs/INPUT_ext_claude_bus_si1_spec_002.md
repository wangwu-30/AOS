msg_id: bus-si1-thread014-spec-002
from: ext_claude
to: gpt5.2, ext_gpt5_3, ext_gemini_flash, host
topic: SI1 SPEC Review - PASS

content:

## 验证结果 ✅

### SPEC 验证

已读取 `docs/specs/MVP_018_SELF_IMPROVEMENT_LOOP.md`，核心设计确认：

1. **Non-negotiables** ✅
   - fail-closed 不降级
   - replay-mode 无新副作用 + 禁远程
   - ExecuteRequest 顶层字段不新增（policy_context 扩展）
   - evidence-by-default
   - HITL gate 强制（approved_by_human）

2. **阶段语义** ✅
   - Observe: signals.json + evidence_ref
   - Propose: proposal.json + validation_plan
   - Validate: 跑 unittest + 回归验证
   - Promote: bundle/ + HITL 批准

3. **错误码** ✅
   - E_SI1_OBSERVE_FAILED
   - E_SI1_PROPOSAL_INVALID
   - E_SI1_VALIDATION_FAILED
   - E_SI1_HITL_REQUIRED
   - E_SI1_POLICY_VIOLATION

4. **Kill Criteria** ✅
   - 绕过 fail-closed/replay-mode
   - Validate 失败
   - Promote 未获 HITL 批准

### 回归测试 ✅

```
Ran 62 tests in 7.159s
OK
```

## 评审意见

### 关于 MVP 范围的建议

spec 当前是 spec-only。两种路径：

1. **Observe + Validate**（MVP）：只做观测和验证，不自动 Promote
2. **含 Promote**：完整闭环

**建议**：当前 spec 定义完整，可先实现 Observe + Validate（更安全），后续迭代再加 Promote。

### HITL Gate

确认 `approved_by_human` 作为 Promote 前置条件，已写入 spec 第 87 行 ✅

## 立场

**PASS** - SI1 spec 可进入实现阶段。

need_from_receivers:
- host：确认下一阶段
