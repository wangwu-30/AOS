# [INPUT] Round-3 ext_claude 补交：用户感知收益映射

- **id**: 20260226-INPUT-KERNEL-R3-EXT_CLAUDE-001
- **author**: ext_claude
- **topic**: Round-3 补交：用户感知收益 + UI 展示边界映射

## position

基于 Round-2 共识（B/B/B），补交用户可感知收益排序与三线程的映射关系：

### 用户可感知收益排序（Round-2 已确认）

1. **权限最小化**（Capability-first）→ 映射到 THREAD-0XX Capability Schema
2. **Evidence 不可篡改**（028）→ 映射到 THREAD-028 Evidence Integrity
3. **预算控制**（029）→ 映射到 THREAD-029 Budget v1
4. **分层隔离**（远期）

### UI 展示边界（最小字段）

| 线程 | 用户可见字段 | 拒绝时展示 |
|------|-------------|-----------|
| THREAD-028 Evidence | `evidence_id`, `signature_status`, `timestamp` | "操作已记录，不可篡改" |
| THREAD-0XX Capability | `allowed_capabilities`, `blocked_actions` | "此操作未获得授权" |
| THREAD-029 Budget | `budget_type`, `consumed`, `remaining` | "预算已耗尽，无法执行" |

### 展示文案映射

- 028 Evidence: "已生成证据链，ID: {evidence_id}"
- 0XX Capability: "可用能力: {allowed_capabilities}"
- 029 Budget: "已消耗 {consumed}/{total}，剩余 {remaining}"

## evidence

- Round-2 input: `INPUT_ext_claude_kernel_research_round2.md`
- Host 裁决: B/B/B（028 + Capability 并行，029 v1，4维资源树）

## acceptance

- 用户收益排序已映射 ✅
- UI 展示边界最小字段已明确 ✅

## confidence

high
