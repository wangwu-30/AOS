# 2026-02-13 并行推进MVP（Parallel MVP Development）

目标（Goal）
- 尽快达成MVP交付：内核（kernel）+ 签名与可信执行（signing + trusted execution）+ 个人助理demo（personal assistant demo）。
- 默认 fail-closed：任何远程模型调用（remote LLM call）必须显式双开关（double gating）。

本轮做法（Approach）
- 采用并行分工（subagents parallelization）拆三条线：
  - 端到端测试：补齐 `mvp run-package` 的可回归断言（stable JSON output + evidence/trace 落盘）。
  - 示例技能包：仓库内置一个可签名验证（ASVP）的 skill package，提交公钥（public key）与签名（signature），不提交私钥（private key）。
  - 个人助理demo：通过同一条内核路径跑示例包（PackageRunner），输出 trace_id 与 evidence_refs 便于验收与调试。
- 受限于当前 subagent 并发上限，测试与示例包交给subagent，demo在主线程实现。

关键取舍（Key Tradeoffs）
- Demo 采用 package-first：直接走 `run-package`/`PackageRunner`，避免“demo绕开可信执行链路”的反模式。
- Demo 默认使用 `local_mock`，并保留 `codex_oauth` 作为可选后端，但仍受双开关和 replay_mode 约束。

产出（Outputs）
- 新增 `mvp assistant-demo` CLI 子命令：`src/agentos_next/cli.py`
- 新增 demo 入口实现：`src/agentos_next/apps/personal_assistant_demo.py`
- 修复循环依赖（circular import）：`src/agentos_next/skills/__init__.py` 不再做 eager re-export
- 优化 `local_mock` 观感：`src/agentos_next/llm/backend.py` 在不破坏 schema 的前提下，让 `reply` 更像真实助理输出
- 远程调用 fail-closed 回归测试：`tests/test_mvp_run_package_codex_gating.py`
- 将 LLM 调用错误收敛为稳定 error_code：`src/agentos_next/skills/llm_execution.py`
- 引入可上线标准与准入测试：`docs/specs/RELEASE_CRITERIA.md`、`docs/specs/ADMISSION_TESTS.md`
- 脱敏（Redaction）落盘前执行并加入准入测试：`src/agentos_next/kernel/redaction.py`、`tests/test_admission_redaction.py`
