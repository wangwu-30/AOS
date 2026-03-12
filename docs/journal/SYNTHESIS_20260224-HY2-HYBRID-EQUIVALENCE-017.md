# SYNTHESIS: HY2 Hybrid/Direct 语义等价

- `thread_id`: `20260224-HY2-HYBRID-EQUIVALENCE-017`
- `updated_at`: `2026-02-24`
- `status`: `resolved`

## 综合结论

- 采用最小 Hybrid runtime（event-dispatch shell）+ direct fallback，保持执行语义不变。
- 在 `HITL_BLOCK` / `REPLAY_BLOCK` / `SCHED_FOLLOWUP_SUCCESS` / `TOOL_FAIL` 四类场景下，direct 与 hybrid 的稳定键等价成立。
- fallback 语义被显式验证：当 Hybrid 运行异常时，可回退到 direct 且结果等价；禁用 fallback 时应抛出错误并 fail-closed。

## 风险与缓解

- 风险：双路径长期漂移。  
  缓解：HY2 等价测试作为回归门禁，覆盖失败路径而非仅成功路径。
- 风险：证据不可追溯。  
  缓解：测试强制验证 `evidence_refs` 对应 meta/blob 存在。

## 验收锚点

- `tests/test_spike_hy2_hybrid_equivalence.py`
- `tests/hybrid_gate_helpers.py`
