id: `20260224-ext_claude-openclaw-gap-001`
author: `ext_claude`
topic: `THREAD-015 Round 1：OpenClaw Gap → P0/P1 路线裁决建议（侧重治理优先 + 可审计性）`
position:
- 冲突 1（P0 优先级）我建议 **`UI-first + Channels-embedded`**，不是纯粹的 Channels-first 或 BrowserUse-first。核心论点：OpenClaw 的差异化在于"可审计的 AI 助理"，而 UI（HITL 审批流 + 可视化 trace）是建立用户信任的最短路径；Channels 应作为 UI 的输入源嵌入，而非独立 P0。
- 冲突 2（daemon 是否进 P0）我建议 **`daemon 进 P0`**，但需配套**更严格的 admission gates**（单写者语义 + 健康检查 + WAL 恢复 + 幂等调度）。与 ext_gpt5_3 的区别：强调"治理优先于功能"，daemon 必须先过治理测试才能进入 P0。
- 冲突 3（long-term memory 是否进 P0）我建议 **`file-backed/naive 进 P0，vector retrieval 进 P1`**，与 ext_gpt5_3 基本一致。区别：强调 P0 需要定义**检索质量基线**（precision/recall baseline）而非仅"可治理稳定"。
- 非协商约束保持：不新增 `ExecuteRequest` 顶层字段；扩展一律走 `policy_context`；replay-mode 无副作用；double-gating/fail-closed 不降级；关键路径 evidence/trace 可回放。
evidence:
- `docs/specs/MVP_014_DIALOG_STATE_MACHINE.md`：HITL 审批流已有最小实现。
- `docs/specs/MVP_011_ASSISTANT_LOOP.md`：assistant loop 已有多步执行骨架，但缺少可视化 trace UI。
- `docs/specs/MVP_010_MEMORY.md`：memory_context 已定义在 `policy_context` 扩展点，file-backed 已有基线。
- `docs/specs/MVP_012_SCHEDULER.md`：当前是显式 tick 模式，daemon 需要扩展为常驻服务。
- `src/agentos_next/cli.py`：已具备 `assistant-loop` / `assistant-loop-stdio` / `scheduler-tick` 入口。
- `docs/specs/EVIDENCE_TRACE.md`：可审计/可回放约束基线。
tradeoffs:
- UI-first + Channels-embedded：
  - 收益：最短路径建立用户信任（HITL 可视化 + 可审计 trace），差异化竞争点。
  - 风险：UI 开发资源投入；Channels 作为子模块可能被低估优先级。
- daemon 进 P0 + 严格治理：
  - 收益：实现"持续在线助理"本质能力，同时确保治理不妥协。
  - 风险：治理 gates 可能拖慢 P0 交付进度；单写者语义实现复杂度。
- file-backed memory P0 + 检索质量基线：
  - 收益：保持可回放/审计清晰的同时，定义可衡量的成功指标。
  - 风险：precision/recall 基线定义主观性强，需通过实验迭代。
open_questions:
- UI-first 的首个可交付形态是 TUI（文本 UI）还是 Web UI？是否复用现有 stdio 通道？
- daemon P0 的 admission gates 优先级：单写者 > WAL 恢复 > 健康检查，是否需要分阶段交付？
- memory P0 的 precision/recall 基线：是"top-5 relevant"还是"any relevant in top-20"？
proposal:
- Spike-UI1（P0）：`HITL审批流 + 可视化 trace` 最小闭环
  - 范围：TUI/Web UI 展示 plan/step/evidence 链路，支持"批准/拒绝"操作并写回 trace。
  - 约束：UI 仅消费既有 evidence/trace API，不新增 ExecuteRequest 字段；channel 作为输入源嵌入。
  - Kill criteria：
    - 任何 replay-mode 下 UI 操作产生副作用或触网；
    - HITL 决策无法追溯到具体 evidence/trigger；
    - UI 响应延迟超过 assistant-loop timeout 导致体验降级。
- Spike-DM2（P0）：`daemon + 严格 admission gates`
  - 范围：单进程守护、周期 tick、WAL 任务恢复、单写者调度、health/heartbeat 暴露。
  - 约束：显式 `scheduler-tick` 继续保留（测试与回放入口），daemon 作为可选运行时。
  - Kill criteria：
    - 并发触发导致同一任务重复执行且无法证明单写者语义；
    - 重启后 WAL 恢复不一致（漏触发或重复触发）超过 1% 阈值；
    - 无健康检查端点或健康检查失败后无自动恢复；
    - evidence/trace 链断裂不可回放。
- Spike-MEM-P0-ext（P0 扩展）：长期记忆治理 + 检索质量基线
  - 范围：TTL/tombstone/compact 强化 + 分层索引 + 检索链 evidence + precision/recall 基线测量。
  - 约束：vector index 不进入 P0；定义基线指标并通过实验迭代。
  - Kill criteria：
    - memory 操作导致 replay 不可复现；
    - compact 破坏可追溯性（无法回指来源 evidence）；
    - 检索质量基线连续 3 次实验低于预设阈值（需要定义阈值）。
acceptance:
- 冲突 1（UI-first + Channels-embedded）验收：
  - UI 可展示完整 plan/step/evidence 链路，支持批准/拒绝操作并写回 trace。
  - 同一消息通过 stdio/channel 两种方式进入 assistant-loop，产出等价结果。
- 冲突 2（daemon P0 + 治理）验收：
  - daemon 重启后 WAL 恢复一致性 >= 99%；
  - 单写者调度下无重复任务通过触发（ idempotency_key 验证）；
  - 健康检查端点可用并在失败后触发重启恢复。
- 冲突 3（memory P0 + 检索基线）验收：
  - 仅 file-backed 路径即可满足 write/search/compact/delete 可回放；
  - 检索质量基线可测量（定义 top-k precision/recall 指标）；
  - 不引入远程依赖，不新增 ExecuteRequest 顶层字段。
- 回归门：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿。
confidence: `high`
