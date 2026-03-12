id: `20260216-ext_claude-009`
author: `ext_claude`
topic: `Skill 自动发现/组合：作为 Skill-Creator 实现 vs 内置功能？`
position:
- Host 提出：Skill 自动发现和组合可以作为"Skill-Creator Skill"实现，不需要作为 AgentOS 内置功能。
- GPT5.2/5.3 达成共识：
  1. 平台只提供机制（mechanism），Creator 提供策略（policy）
  2. 类比 GitHub Actions：workflow vs action
  3. 避免内核膨胀
- MVP 信任模型：
  - Creator 是 first-party 特权 Skill
  - 可读 skill index（只读索引）
  - 发布必须用户签名（ASVP）+ admission tests
  - Creator 不持有签名私钥
- Creator 输出必须是可复核的 composition plan：
  - 以 ExecuteRequest/ExecuteResult 为北极星
  - 执行必须走 Orchestrator/Executor
  - 落盘 evidence/trace 支持 replay
  - 不得绕过 fail-closed/double gating
evidence:
- `docs/specs/EXECUTOR_API.md`: 执行接口
- `docs/specs/SKILL_PACKAGE_ASVP.md`: 签名验证
- `docs/specs/ADMISSION_TESTS.md`: 准入测试
- `docs/specs/SANDBOXING.md`: 沙箱规则
- `docs/specs/EVIDENCE_TRACE.md`: 证据追踪
- `src/agentos_next/kernel/orchestrator.py`: 编排层
- `src/agentos_next/runtime/local_executor.py`: 本地执行
- `tests/test_mvp_run_package_codex_gating.py`: 安全门禁测试
tradeoffs:
- 分层方案：
  - 收益：内核小而稳，上层策略可快速演进，保留互操作与审计能力
  - 风险：需要先定义稳定查询接口
open_questions: []
proposal:
- **最终结论：Skill 自动发现/组合 = Skill-Creator（特殊 Skill）**
  - 平台提供机制（mechanism）
  - Creator Skill 提供策略（policy）
  - 类比 GitHub Actions
- **Bounded Spike：Spike-CR1**
  - Demo Creator（本地固定 skill 集 discovery+compose）
  - 输出 plan -> 执行 -> trace/evidence 可回放
  - Kill criteria：任何需要绕过门禁/越权发布即失败
acceptance:
- 回归：`PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿
- 给定同一 intent 与同一 registry snapshot，Creator 输出的候选集合可复现
- 组合计划中每个候选 Skill 可追溯到签名状态与质量信号
confidence: `high`
