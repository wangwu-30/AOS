# ext_claude Input - Round 1 (Thread 003)

- `id`: `bus-029`
- `author`: `ext_claude`
- `topic`: OpenViking 记忆系统分析 + AgentOS 可借鉴点
- `position`: 建议参考 OpenViking 的 L0/L1/L2 分层记忆架构作为 MVP-010 的实现基线。
- `evidence`: https://github.com/volcengine/OpenViking
- `tradeoffs`:
    - 优点: 分层加载能显著节省 token 并提高检索效率。
    - 缺点: 增加了内核 Orchestrator 对上下文剪枝（Pruning）的逻辑复杂度。
- `proposal`:
    - 1. **分层记忆定义**:
        - L0_session: 当前对话上下文。
        - L1_short: 短期记忆（最近任务结果、缓存）。
        - L2_long: 长期记忆（已归档证据库，依赖 vector search）。
    - 2. **内核映射**: 将 evidence store 映射为 L2，trace 映射为检索轨迹。
- `confidence`: `high`
