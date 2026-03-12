# SYNTHESIS: THREAD-030 Capability Schema v1（policy_context.capabilities[]）

- `thread_id`: `20260226-CAPABILITY-SCHEMA-030`
- `updated_at`: `2026-02-26`
- `status`: `resolved`

## 综合结论

- Kernel PEP 引入 capability schema v1：`policy_context.capabilities[]` 作为唯一权限声明入口。
- PEP 默认拒绝（default deny）：缺失 required capabilities 的请求必须 fail-closed，并写 policy evidence + trace。
- 高风险审批路径不另造轮子：复用 `E_HITL_REQUIRED`，避免同义错误码扩散。

## v1 关键冻结点

- schema：
  - capabilities 为 list；每项必须为 object，包含 `name` 与 `scope`
  - `name` 必须在 allowlist；未知名称 -> `E_CAPABILITY_SCHEMA_INVALID`
- required mapping（v1）：
  - `builtin://memory.{write,delete,compact}` -> `memory_write`
  - `builtin://scheduler.{at,cron}` -> `scheduler_write`
  - `allow_network_egress=true` -> `net_egress`
  - `remote_calls_armed=true` 或 `backend=codex_oauth` -> `llm_remote`
- 错误码：
  - missing => `E_CAPABILITY_DENY`
  - invalid schema => `E_CAPABILITY_SCHEMA_INVALID`

## Gate（通过条件）

1. 不新增 ExecuteRequest 顶层字段（policy_context-only）
2. 拒绝路径稳定 error_code + evidence + trace（无 traceback）
3. 回归全绿

## 验收锚点

- `tests/test_thread030_capability_schema.py`
- `src/agentos_next/kernel/policy_engine.py`
- `docs/specs/MVP_030_CAPABILITY_SCHEMA.md`

