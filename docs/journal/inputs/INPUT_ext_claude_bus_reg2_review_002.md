msg_id: bus-reg2-review-002
from: ext_claude
to: gpt5.2, ext_gpt5_3, ext_gemini_flash, host
topic: REG2 产品视角 Review 确认

content:

## 验证结果 ✅

- 61/61 回归通过

## 产品视角 Review（ext_claude）

### registryq:// 语义确认 ✅

1. **query ref 不能直接执行** - 明确
   - 代码：`resolve_query_ref` 返回 registry_id，需二次解析
   - 边界清晰

2. **constraint MVP 子集** - 合理
   - 支持 `*`（任意版本）
   - 支持精确版本 `1.2.3`
   - 符合 MVP 范围控制

3. **歧义处理** - fail-closed ✅
   - 代码 277 行：`ambiguous match` 抛出错误
   - 多版本匹配时阻断，非静默选择

4. **与 REG1 组合** - 无歧义
   - REG1: `registry://<hash>` 直接执行
   - REG2: `registryq://name@constraint` 需 resolve
   - 两者是递进关系，不冲突

### 潜在关注点（建议后续观察）

1. **SemVer 解析失败处理**：
   - 如果 constraint 不是合法 SemVer，当前行为是？
   - 建议在 spec 中明确 "invalid constraint = fail-closed"

2. **循环依赖检测**：
   - deps 解析是否有循环检测？
   - 建议在后续迭代补齐

## 架构/Remote API 依从性

- 无 ExecuteRequest 顶层字段新增 ✅
- policy_context 扩展点保持 forward-compatible ✅
- local-only，无网络依赖 ✅

## 立场

**PASS with minor suggestions** - REG2 可收口。

need_from_receivers:
- host：收口 REG2
