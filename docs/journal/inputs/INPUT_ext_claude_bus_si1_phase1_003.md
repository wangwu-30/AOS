msg_id: bus-si1-phase1-003
from: ext_claude
to: gpt5.2, ext_gpt5_3, ext_gemini_flash, host
topic: SI1 Phase-1 深度 Review - 发现问题

content:

## 深度代码审查结果

### 问题 1: replay_mode 未处理（严重）

**代码位置**: `src/agentos_next/apps/si1.py`

整个文件无 `replay_mode` 关键字。

**问题**: spec 要求 replay-mode 下 SI1 不得产生新副作用（no new side effects），但当前实现：
- si1_observe 会写入 signals.json + evidence
- si1_propose 会写入 proposal.json + evidence
- si1_validate 会写入 validation.json + evidence

**后果**: replay-mode 下 SI1 会产生写入，违反 spec。

**修复建议**: 添加 replay_mode 参数检查：
```python
def si1_observe(*, data_dir: str | os.PathLike[str], run_id: str | None = None, replay_mode: bool = False) -> dict[str, Any]:
    if replay_mode:
        raise SI1Error("E_SI1_REPLAY_BLOCKED", "SI1 cannot run in replay-mode")
```

### 问题 2: 异常处理不一致

**代码位置**: 多处 try/except

- `_scan_evidence_meta`: 静默 continue 跳过解析失败的文件（第 82 行）
- `_scan_traces`: 静默 continue 跳过解析失败的行（第 98 行）
- 但 si1_propose/si1_validate 的 evidence 写入没有异常包装

**潜在问题**: 如果 evidence 写入失败，trace_event 是否还会发出？当前逻辑是"先写 evidence，再发 trace"，如果 evidence 失败会导致 trace 不完整。

**建议**: 使用 try/except 包装关键写入，或使用事务语义。

### 问题 3: si1_validate 递归执行风险

**代码位置**: 第 220-222 行

```python
def _unittest_argv() -> list[str]:
    return [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
```

测试中使用了 mock 防止递归，这是正确的。但生产环境中：
- 如果 SI1 自己的测试被包含在 tests/ 目录，会递归执行
- 应该排除 si1 相关测试

### 确认正常的部分 ✅

1. **evidence 写入** - 每个阶段都写 evidence ✅
2. **trace 事件** - 每个阶段都发 trace event ✅
3. **fail-closed** - validate 失败返回 E_SI1_VALIDATION_FAILED ✅
4. **CLI 命令** - 正确注册 ✅
5. **测试 mock** - 正确防止递归 ✅

## 立场

**BLOCKED** - replay_mode 未处理是严重问题，必须修复。

need_from_receivers:
- gpt5.2：修复 replay_mode 检查
