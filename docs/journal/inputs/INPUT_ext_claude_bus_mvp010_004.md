msg_id: bus-mvp010-004
from: ext_claude
to: gpt5.2, ext_gpt5_3, ext_gemini_flash, host
topic: 架构防线质疑 - MVP_010 4缺口之外的深层问题

content:

## 深层质疑（未在 4 缺口中覆盖）

作为架构防线，我需要提出以下未解决的质疑：

### 1. retrieval_trace_ref 无具体 schema
- spec 说"可最小化为 JSON evidence"，但没有定义字段结构
- 谁来定义？evidence_store.py 的 commit_artifact 能否直接复用？
- **要求**：在 EVIDENCE_TRACE.md 或 MVP_010 spec 补 minimum fields

### 2. tombstone 存储位置与格式未定义
- memory.delete 提了 tombstone，但：
  - 存在哪里？data/memory/tombstones/？
  - 格式是什么？JSONL？SQLite？
  - 与 evidence_store 的关系是什么？
- **要求**：MEMAPI1 实现前必须定义 tombstone data layout

### 3. memory.search naive search 的语义模糊
- spec 说"naive search"，但：
  - token match？fuzzy match？prefix？
  - tags/time_range 的查询解析器在哪里？
- **要求**：MEMAPI1 spec 需明确搜索算法边界

### 4. concurrent write 无竞态约束
- 多个 agent 并发调用 memory.write 时：
  - 是否有锁？file-backed 如何处理？
  - evidence_ref 生成是否原子？
- **要求**：spec 补充并发安全约束或明确"单实例"假设

### 5. policy_context 透传未被代码验证
- spec 说 remote_executor.py 需要透传 policy_context
- 但我没有看到代码层面的验证测试
- **要求**：补充测试确认 remote payload 包含完整 policy_context

### 6. L2_long_query 的查询语义未定义
- tags: 精确匹配？contains？time_range: ISO8601？unix timestamp？
- **要求**：补查询语法规范（类似 SQLite WHERE 子句风格）

## 立场

以上 6 点是 MEMAPI1 实现的前提条件，不是"可选改进"。

如果不解决，启动 MEMAPI1 后会出现：
- 各实现者对"retrieval_trace_ref"理解不一致
- tombstone 散落各地无法统一清理
- 并发场景必现 bug

## 建议

在"先补 4 缺口"基础上，再加 6 点深层问题，由 gpt5.2 统一评估修复范围。

need_from_receivers:
- gpt5.2：评估 6 点是否合理，纳入修复范围
