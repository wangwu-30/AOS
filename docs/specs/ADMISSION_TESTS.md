# 准入测试（Admission Tests）

本规范定义“可上线标准”的自动化准入测试集合（admission tests）。

本规范是 `docs/specs/RELEASE_CRITERIA.md` 的“可自动化子集”，用于将上线门槛固化为可执行的阻断门（block release）。

## 范围（Scope）

- 准入测试 MUST 覆盖：
  - 签名与验证（ASVP, signing/verification）
  - 证据与追踪（Evidence/Trace）落盘与基本结构稳定性
  - 远程调用默认禁止（fail-closed）与双开关（double gating）
  - Demo 可运行且不依赖网络/Token（local_mock）

## 命名与执行（Naming & Execution）

- 测试文件 SHOULD 使用 `tests/test_admission_*.py` 命名。
- 执行方式 MUST 为 stdlib `unittest`：
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v`
  - 也可以（MAY）只执行 admission tests 子集（推荐用于默认阻断门）：
	    - `PYTHONPATH=src python3 -m unittest discover -s tests -v -p 'test_admission_*.py'`
	    - 或 `PYTHONPATH=src python3 -m agentos_next.cli mvp release-pack`

## 最小断言（Minimal Assertions）

- ASVP：
  - 对 `examples/skills/personal_assistant_brief` 启用 `--verify-asvp` MUST 通过。
- Evidence：
  - `data/evidence/meta/<ref>.json` MUST 存在并包含字段：
    - `ref`、`kind`、`ts`、`content_type`、`size_bytes`
- Trace：
  - `data/traces/<trace_id>.jsonl` MUST 存在。
  - 每行 MUST 为可解析 JSON（valid JSON）。
  - 每条事件 MUST 至少包含字段：
    - `schema_version`、`event_type`、`ts`、`ctx.trace_id`、`ctx.turn_id`、`ctx.span_id`

## 失败策略（Failure Policy）

- 准入测试失败 MUST 阻断上线（block release）。
