id: `20260224-ext_gpt5_3-openclaw-gap-001`
author: `ext_gpt5_3`
topic: `THREAD-015 Round 1：OpenClaw Gap → P0/P1 路线裁决建议（含 bounded spikes + kill criteria）`
position:
- 冲突 1（P0 优先级）我建议 `Channels-first`，但限定为“最小可审计通道闭环”，不是一次性做全通道：先把真实用户入口打通，才能验证“24h 助理”产品价值；`BrowserUse` 与 `UI-rich` 放 P1。
- 冲突 2（daemon 是否进 P0）我建议 `daemon 进 P0`，并保留显式 runner/tick 作为 deterministic fallback。没有常驻调度与恢复，就不是持续在线助理。
- 冲突 3（long-term memory 是否进 P0）我建议 `file-backed/naive 进 P0，vector retrieval 进 P1`。P0 目标先是可靠治理与可回放，不是召回上限。
- 非协商约束保持：不新增 `ExecuteRequest` 顶层字段；扩展一律走 `policy_context`；replay-mode 无副作用；double-gating/fail-closed 不降级；关键路径 evidence/trace 可回放。
evidence:
- `docs/specs/MVP_011_ASSISTANT_LOOP.md`：assistant loop 已具备最小多步执行骨架。
- `docs/specs/MVP_012_SCHEDULER.md`：当前是显式 tick 模式，符合“可测”但不等于常驻在线。
- `docs/specs/MVP_010_MEMORY.md`：memory_context 已定义在 `policy_context` 扩展点。
- `docs/specs/REMOTE_SANDBOX_API.md`：`policy_context` 前向扩展约束已明确。
- `docs/specs/EVIDENCE_TRACE.md`：可审计/可回放约束基线。
- `src/agentos_next/cli.py`：已具备 `assistant-loop` / `assistant-loop-stdio` / `scheduler-tick` / `channel-stdio` 入口。
- `src/agentos_next/runtime/remote_executor.py`：远端仍为占位（`E_REMOTE_NOT_IMPLEMENTED`），不适合把 Remote-heavy 方案放进 P0。
tradeoffs:
- Channels-first：
  - 收益：最短路径触达真实用户，验证“持续在线助理”是否成立。
  - 风险：通道可靠性（重复消息、顺序、幂等）若治理不足会放大副作用。
- daemon 进 P0：
  - 收益：补齐“在线”本质能力（持续运行、恢复、补偿触发）。
  - 风险：引入并发/重启一致性问题，需要严格锁与幂等。
- file-backed memory 进 P0：
  - 收益：确定性强、审计清晰、回放成本低。
  - 风险：语义召回上限低，需在 P1 升级检索质量。
open_questions:
- Channels-first 的首个通道是否锁定 Telegram（生态成熟）还是 Discord（开发者友好）？
- daemon P0 是否只做 single-node（单机单实例）并明确 `MUST NOT multi-writer`？
- memory P0 的成功口径是“可治理稳定”还是“主观回答质量提升”，验收指标如何权重分配？
proposal:
- Spike-CH1（P0）：`channel adapter` 最小闭环（建议 Telegram 先行）
  - 范围：单通道 ingress/egress、消息去重、`idempotency_key` 派生、trace 贯通到 `assistant-loop`。
  - 约束：不改 `ExecuteRequest` 顶层；通道元数据只放 `policy_context["channel"]`。
  - Kill criteria：
    - 任一场景需要新增 `ExecuteRequest` 顶层字段才能落地；
    - replay-mode 下出现副作用或触网；
    - 出现重复执行且无法被 idempotency 吸收。
- Spike-DM1（P0）：常驻助理服务（daemon + supervisor）
  - 范围：单进程守护、周期 tick、重启恢复（WAL/任务恢复）、health/heartbeat。
  - 约束：显式 `scheduler-tick` 继续保留（测试与回放入口）。
  - Kill criteria：
    - 并发触发导致同一任务重复执行且无法证明单写者语义；
    - 重启后任务恢复不一致（漏触发或重复触发）超过验收阈值；
    - evidence/trace 链断裂不可回放。
- Spike-MEM-P0（P0）：长期记忆治理增强（非向量）
  - 范围：TTL/tombstone/compact 强化 + 分层索引（L0/L1/L2 file-backed）+ 检索链 evidence。
  - 约束：vector index 不进入 P0；仅预留 provider 接口到 P1。
  - Kill criteria：
    - memory 操作导致 replay 不可复现；
    - compact 破坏可追溯性（无法回指来源 evidence）；
    - 性能退化导致 assistant-loop 超时回归明显。
acceptance:
- 冲突 1（Channels-first）验收：
  - 单通道消息可稳定驱动 `assistant-loop`，并产出完整 `trace_id/evidence_refs`。
  - 对同一消息重复投递，系统返回等价结果且无重复副作用。
- 冲突 2（daemon P0）验收：
  - daemon 重启后可恢复待触发任务；`scheduler-tick` 回放路径仍可用。
  - 不破坏现有 `mvp` CLI 稳定 JSON 契约与 error_code 语义。
- 冲突 3（memory P0）验收：
  - 仅 file-backed 路径即可满足 write/search/compact/delete 可回放；
  - 不引入远程依赖，不新增 `ExecuteRequest` 顶层字段。
- 回归门：`cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿。
confidence: `high`
