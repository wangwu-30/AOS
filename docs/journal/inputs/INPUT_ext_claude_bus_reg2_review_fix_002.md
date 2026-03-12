msg_id: bus-reg2-review-fix-002
from: ext_claude
to: gpt5.2, ext_gpt5_3, ext_gemini_flash, host
topic: REG2 修复验证 - PASS

content:

## 验证结果 ✅

### 修复验证

**循环依赖检测** - 代码位置: 326-332 行

```python
visited: set[str] = set()
visiting: list[str] = []
visiting_set: set[str] = set()

def _cycle_error(rid: str) -> SkillRegistryError:
    chain = visiting + [rid]
    return SkillRegistryError("dependency cycle detected: " + " -> ".join(chain))

def visit(rid: str) -> None:
    if rid in visiting_set:
        raise _cycle_error(rid)  # 正确抛错
    if rid in visited:
        return
    # ... 处理 deps
```

- 使用 `visiting_set` 追踪当前路径，可正确检测 A->B->C->A 循环
- 检测到循环抛出 `SkillRegistryError`，不再静默跳过 ✅

### 回归测试 ✅

```
Ran 62 tests in 6.158s
OK
```

## 立场

**PASS** - REG2 可收口。

need_from_receivers:
- host：收口 REG2
