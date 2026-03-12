# DECISIONS: GT2 Golden Trace 量化门禁

- `thread_id`: `20260224-GT2-GOLDEN-TRACE-GATE-018`
- `updated_at`: `2026-02-24`
- `status`: `accepted`

## Decision 001: GT2 是否采用量化阈值门禁

- **状态**: `accepted`
- **结论**: 接受（A）
  - 采用硬阈值：`flake<=1%` + `连续10次通过` + `连续2次失败触发回退`
  - 必须输出结构化 gate report 以支持审计与收口。

## Decision 002: GT2 是否允许网络依赖

- **状态**: `accepted`
- **结论**: 拒绝网络依赖（B）
  - GT2 回归必须在本地 deterministic 环境完成；
  - 远程依赖会引入噪声，不可作为 P0 门禁依据。

## Gate

1. 失败路径必须纳入 GT 统计（不得只测 happy path）。
2. 回退触发必须可执行（连续失败计数）。
3. 不新增 ExecuteRequest 顶层字段。

## Acceptance

- `tests/test_spike_gt2_golden_trace_gate.py` 通过
- `cd agentos-next && PYTHONPATH=src python3 -m unittest discover -s tests -v` 全绿

## Non-Negotiables (Tokens)

- `top_level_api_stable`
- `fail_closed`
- `replay_mode_no_side_effects`

