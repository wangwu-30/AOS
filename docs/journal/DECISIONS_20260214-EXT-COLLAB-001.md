# Decisions

- `thread_id`: `20260214-EXT-COLLAB-001`
- `updated_at`: `2026-02-14`
- `status`: `finalized`

## Decision 001: 协作协议先文档化落盘

- 状态：`accepted`
- 结论：
  - 先落地 `docs/specs/EXPERT_COLLAB_PROTOCOL.md` 与线程配套文件，作为后续多专家协作统一入口。
- 原因：
  - 当前最小代价即可提升协作可审计性与一致性。
- 拒绝的备选：
  - 跳过协议直接收集聊天结论（不可追踪，拒绝）。
- 验收：
  - 协议文件与线程文件按命名规范存在。
  - 专家输入满足 Message Contract 字段要求。

## Decision 002: 协议自动化准入

- 状态：`accepted`
- 结论：
  - 将“协作协议合规”纳入 admission tests 的最小门禁（文件存在、thread 元字段可解析、成套文档存在、至少一个输入满足 Message Contract + confidence 值域）。
- 证据：
  - `tests/test_admission_expert_collab_protocol.py`
- 限界实验（Bounded Spike）：
  - 实验 A：加入最小文档契约测试，观察维护成本与误报率。
  - 结果：当前误报/维护成本可控，满足推进门槛。
  - Kill criteria：若新增维护成本高于当前收益且误报不可控，则暂缓（保留为后续回滚门）。

## Decision 003: PackageRunner/Executor 语义收敛

- 状态：`accepted`
- 结论：
  - 采用方案 B：优先实现 `LocalExecutor.execute -> PackageRunner` 适配，作为 `ExecuteRequest/ExecuteResult` 统一语义的首个执行落点。
- 原因：
  - 以 `Executor API` 作为北极星更利于长期收敛，避免映射层长期“被动存在”而再次漂移。
  - 当前已具备 bounded spike 证据，可在不破坏现有主路径语义的前提下推进适配。
- 评分矩阵（Evidence Scoring Matrix）：
  - 安全与治理（Security/Governance）：`32/35`
  - 可验证性（Verifiability）：`28/30`
  - 实施成本（Implementation Cost）：`15/20`
  - 交付速度（Delivery Speed）：`13/15`
  - 总分：`88/100`（通过 Decision Gate：总分 `>=80` 且 Security `>=30`）
- 单一硬回退阈值（hard rollback trigger）：
  - 若 `LocalExecutor` 适配导致 `src/agentos_next/runtime/package_runner.py` 的既有 CLI JSON 输出字段或 evidence/trace 落盘 schema 发生破坏性变化，则立即回退并将该议题状态恢复为 `needs_decision`。
- 证据：
  - `docs/journal/inputs/INPUT_ext_gpt5_2.md`（`id: 20260214-ext_gpt5_2-003`）
  - `src/agentos_next/runtime/execute_mapping.py`
  - `tests/test_spike_executor_mapping.py`
  - `tests/test_mvp_rc_pack.py`

## Decision 004: Architecture Alignment Final（supersedes Decision 003 execution path）

- 状态：`accepted`
- 结论：
  - 过渡主路径采用 A：优先在 `mvp rc-pack` 产出 `execute_result.json`（ExecuteResult 形状）作为默认审计材料。
  - 方案 B（`LocalExecutor.execute -> PackageRunner`）保留为并行补充路线，仅以 bounded spike 推进，不作为当前主路径。
- supersedes：
  - 本决策仅覆盖 Decision 003 中“执行主路径选择”；Decision 003 的不变量与回退思想继续有效。
- 原因：
  - `rc-pack` 作为 RC 证据入口天然适合作为语义落点，且对现有 `PackageRunner` 执行主路径侵入最小。
  - 专家最终口径中，`ext_gpt5_2` 给出唯一主路径选择 A，并提供硬回退阈值；`ext_claude` 存在互相冲突口径（`-001/-002` 与 `-003`），按协议优先采用“可验证且满足决策门约束”的方案。
- 单一硬回退阈值（hard rollback trigger）：
  - 若为生成 `execute_result.json` 必须修改 `src/agentos_next/runtime/package_runner.py` 的对外行为（`mvp run-package` CLI JSON 字段或 evidence/trace 落盘 schema 的 breaking change），立即回退 A 主路径并将该议题状态恢复为 `needs_decision`。
- 证据：
  - `docs/journal/inputs/INPUT_ext_gpt5_2.md`（`id: 20260214-ext_gpt5_2-005`）
  - `docs/journal/inputs/INPUT_ext_claude.md`（`id: 20260214-ext_claude-001`、`id: 20260214-ext_claude-002`、`id: 20260214-ext_claude-003`）
  - `src/agentos_next/runtime/execute_mapping.py`
  - `tests/test_spike_executor_mapping.py`
  - `tests/test_mvp_rc_pack.py`

## Decision 005: Human Override（supersedes Decision 004）

- 状态：`accepted`
- 结论：
  - 拒绝 Decision 004。
  - 采用 Claude 提议方向：不以过渡方案作为主路径，启动 bounded spike 直接验证 `Orchestrator -> Executor` 调用链，并验证 `PackageRunner` 可被 `LocalExecutor` 语义替换。
- supersedes：
  - 本决策覆盖 Decision 004 的“主路径选择”。
  - Decision 001/002 保持有效（协作协议与最小 admission MUST 不变）。
- 人类裁决（Human Arbitration）：
  - 你已明确表达“赞同 Claude 方案”，因此本项按协议由人类裁决直接生效。
- Bounded Spike：
  - Spike-005A：实现最小 `Orchestrator -> Executor` 直连路径（可为库入口或受控 CLI 子命令），验证执行链闭环。
  - Spike-005B：在不破坏既有契约的前提下，验证 `PackageRunner` 能被 `LocalExecutor` 覆盖语义（允许内部复用，不要求一次性删除）。
- Kill criteria（来自 Claude 并作为硬回退）：
  - 若 spike 期间破坏现有 CLI 稳定 JSON 输出或 evidence/trace 落盘 schema，则立即回退并将议题状态恢复为 `needs_decision`。
- Acceptance（可执行验收命令，Executable Acceptance）：
  - `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v`
- 证据：
  - `docs/journal/inputs/INPUT_ext_claude.md`（`id: 20260214-ext_claude-003`）
  - 人类消息（本线程）：`我赞同他的方案`

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`
