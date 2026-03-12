# MVP_012_SCHEDULER

- 状态（Status）：Draft
- 日期（Date）：2026-03-10
- 目标版本（Target）：MVP_012
- 相关规范（Related Specs）：
  - `docs/specs/MVP_011_ASSISTANT_LOOP.md`
  - `docs/specs/MVP_044_PA_POLLING_MODE.md`

## 目的（Purpose）

定义最小调度器（Scheduler）能力，使系统能够持久化延迟/定时触发，并在到期时复用 canonical runtime 的执行语义。

## 接口（Interfaces）

- `builtin://scheduler.at`
- `builtin://scheduler.cron`

最小 `execute_request` 草案字段（MUST）：
- `operator_ref`
- `arguments`
- `deadline_ms`
- `policy_context`
- `preferred_target`

## 调度语义（Scheduling Semantics）

- scheduler 只负责“何时触发”，不得（MUST NOT）承担渠道适配逻辑。
- 到期触发时必须（MUST）通过 `Orchestrator.execute(ExecuteRequest)` 执行。
- reminder 场景必须（MUST）把 `execute_request.operator_ref` 设为 `builtin://channel.send_message`，不得（MUST NOT）再写入 `builtin://telegram.send_message`。
- 若 reminder 目标渠道是 Telegram，必须（MUST）通过 `arguments.metadata.channel="telegram"` 与 `arguments.metadata.conversation_id` 保留投影信息，真正投递由 Consumer Adapter 决定。

## 默认值（Defaults）

- `deadline_ms = 60000`
- `preferred_target = "local"`
- `timezone = "UTC"`（cron v1）

## 错误码（Error Codes）

- `E_INPUT_SCHEMA`
- `E_SCHED_CRON_UNSUPPORTED`
- `E_EXECUTION_FAILED`
- `E_TIMEOUT`

## 边界条件（Boundary Conditions）

- replay-mode 下 scheduler tick 不得（MUST NOT）产生副作用。
- `workspace_id`、安全关键 `policy_context` 字段必须（MUST）由 scheduler 强制覆盖，不能被任务草案提升权限。
- cron 超出子集时必须（MUST）fail-closed。

## 兼容策略（Compatibility）

- 任务存储格式可保持不变，但新写入不得（MUST NOT）再包含 `builtin://telegram.*`。
- 历史调度记录若仍包含 `builtin://telegram.*`，不属于本规范保证范围。

## 测试与验收（Tests/Acceptance）

必须（MUST）满足：
1. `scheduler.at` 创建任务后可在 tick 时触发执行。
2. reminder 任务的新写入必须是 `builtin://channel.send_message`。
3. 重复 tick 不得产生重复副作用。

验收命令（MUST）：
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread033_pa_ev1_runtime -v`
