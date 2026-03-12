# MVP_051_RUNTIME_POLICY_BUNDLE

- 状态（Status）：Draft
- 日期（Date）：2026-03-12
- 目标版本（Target）：MVP_051
- 相关规范（Related Specs）：
  - `docs/specs/MVP_045_QUERY_GATED_RUNTIME.md`
  - `docs/specs/MVP_046_AGENT_AXIOMS_CONTEXT_PLANES.md`
  - `docs/specs/MVP_054_EXPLICIT_RESEARCH_RUN.md`
  - `docs/specs/LLM_PROVIDER.md`

## 目的（Purpose）

定义运行时策略包（Runtime Policy Bundle）的 canonical 形状，使查询编译（Query Compile）能够在不新增 `ExecuteRequest` 顶层字段的前提下，吸收用户偏好画像（User Preference Profile）、执行模式策略（Execution Mode Policy）、数据敏感度策略（Data Sensitivity Policy）与主动策略（Proactivity Policy）。

## 接口/数据结构（Interfaces/Data）

### RuntimePolicyBundleV1（MUST）

```json
{
  "schema_version": "1.0.0",
  "workspace_policy_id": "string",
  "workspace_scope": "string",
  "user_preference_profile": {
    "communication_style": ["string"],
    "response_language": "string|null",
    "active_hours_local": [9, 10],
    "preferred_topics": ["string"],
    "risk_tolerance": "low|balanced|high"
  },
  "execution_mode_policy": {
    "default_mode": "cost_saver|balanced|quality_first|chat_first",
    "allow_user_override": true
  },
  "data_sensitivity_policy": {
    "default_level": "L0|L1|L2",
    "storage_policy": {
      "L0": "process_only",
      "L1": "local_only",
      "L2": "local_or_sync"
    },
    "external_transfer_requires_confirmation": true
  },
  "proactivity_policy": {
    "enabled": false,
    "quiet_hours_local": [0, 1],
    "notify_on_mentions_only": true,
    "max_pushes_per_day": 0
  },
  "external_evidence_policy": {
    "search_rounds_max": 2,
    "browse_candidates_per_search_max": 3,
    "total_browse_steps_max": 4
  }
}
```

### Query Compile 投影（MUST）

- Query Compile 必须（MUST）按 `workspace_id` 解析一个 `RuntimePolicyBundleV1`，缺失时必须（MUST）回退到 repo 默认 bundle。
- Query Compile 必须（MUST）把 `user_preference_profile.communication_style` 投影到 `communication_plane.communication_style` 或等价上下文。
- 当调用方未显式提供 `response_language` 时，Query Compile 必须（MUST）使用 `user_preference_profile.response_language` 作为默认值。
- Query Compile 必须（MUST）把 `execution_mode_policy.default_mode` 投影到 `model_routing_policy.execution_mode`。
- Query Compile 必须（MUST）把 `risk_tolerance`、`default_mode` 与 `default_level` 作为可审计策略事实进入 query 产物。
- Query Compile 对 `requires_external_evidence=true` 的任务必须（MUST）把 `external_evidence_policy` 投影为 `task_requirements.external_evidence_policy_v1`。
- 当单次请求提供 `external_evidence_policy_v1` 覆盖时，Query Compile 必须（MUST）以单次请求值覆盖 bundle 默认值。
- Runtime Policy Bundle 不得（MUST NOT）直接改写 `AgentProfileV2.execution_axioms`、`SoulProfileV2.global_soul` 或 `EffectiveRuntimeCapabilitiesV1`。
- Runtime Policy Bundle 不得（MUST NOT）携带 `research_required`、`selected_doctrine_pack`、`self_adversarial_required` 或等价 research/adversarial 算法控制字段。

## 默认值（Defaults）

- `schema_version = "1.0.0"`
- `workspace_policy_id = "default"`
- `user_preference_profile.communication_style = ["clear", "honest", "concise"]`
- `user_preference_profile.response_language = null`
- `user_preference_profile.active_hours_local = []`
- `user_preference_profile.preferred_topics = []`
- `user_preference_profile.risk_tolerance = "balanced"`
- `execution_mode_policy.default_mode = "balanced"`
- `execution_mode_policy.allow_user_override = true`
- `data_sensitivity_policy.default_level = "L1"`
- `data_sensitivity_policy.storage_policy.L0 = "process_only"`
- `data_sensitivity_policy.storage_policy.L1 = "local_only"`
- `data_sensitivity_policy.storage_policy.L2 = "local_or_sync"`
- `data_sensitivity_policy.external_transfer_requires_confirmation = true`
- `proactivity_policy.enabled = false`
- `proactivity_policy.quiet_hours_local = []`
- `proactivity_policy.notify_on_mentions_only = true`
- `proactivity_policy.max_pushes_per_day = 0`
- `external_evidence_policy.search_rounds_max = 2`
- `external_evidence_policy.browse_candidates_per_search_max = 3`
- `external_evidence_policy.total_browse_steps_max = 4`

## 错误码（Error Codes）

- 本规范当前不得（MUST NOT）新增阻断主链的错误码。
- 当 bundle 缺失、损坏或字段非法时，运行时必须（MUST）回退默认 bundle，而不是让 Query Compile 失败。

## 边界条件（Boundary Conditions）

- `active_hours_local` 与 `quiet_hours_local` 的条目必须（MUST）位于 `[0, 23]`。
- `execution_mode_policy.default_mode` 只能（MUST）为 `cost_saver|balanced|quality_first|chat_first`。
- `user_preference_profile.risk_tolerance` 只能（MUST）为 `low|balanced|high`。
- `data_sensitivity_policy.default_level` 只能（MUST）为 `L0|L1|L2`。
- `external_evidence_policy.search_rounds_max` 只能（MUST）位于 `[1, 6]`。
- `external_evidence_policy.browse_candidates_per_search_max` 只能（MUST）位于 `[1, 10]`。
- `external_evidence_policy.total_browse_steps_max` 只能（MUST）位于 `[1, 12]`。
- `proactivity_policy` 在阈值、调度回流与权限策略未冻结前，只能（MUST）作为声明性约束进入 query/context；不得（MUST NOT）直接触发强主动外发。
- Runtime Policy Bundle 不得（MUST NOT）引入第二套 router/executor/verifier 命名或绕过 canonical prompt profiles。
- Runtime Policy Bundle 不得（MUST NOT）替代研究教义（Research Doctrine）或自对抗模式（Self-Adversarial Mode）的选择逻辑。

## 兼容策略（Compatibility）

- Runtime Policy Bundle 必须（MUST）通过 `workspace_id -> bundle` 的方式装配，不得破坏现有 `AgentProfileV2`、`SoulProfileV2` 与 `RuntimeSnapshotV1`。
- Runtime Policy Bundle 必须（MUST）作为 `policy_context` / query 产物的增量扩展；不得（MUST NOT）新增 `ExecuteRequest` 顶层字段。
- 对主动性、数据敏感度与执行模式的首版接入可以（MAY）先以声明性投影为主，后续再扩展为硬裁决或调度策略。
- `external_evidence_policy` 只负责普通外部证据预算默认值；不得（MUST NOT）改变 `research_required` 判定或强制暴露 `builtin://research.run`。

## 测试与验收（Tests/Acceptance）

必须（MUST）满足：
1. 缺失工作区 bundle 时，运行时回退 repo 默认 bundle。
2. 工作区 bundle 覆盖 `response_language` 与 `communication_style` 时，Query Compile 结果必须反映到 `prompt_compilation` 与 `active_style_pack`。
3. `execution_mode_policy.default_mode` 必须进入 `model_routing_policy`。
4. `external_evidence_policy` 默认值必须进入 `task_requirements.external_evidence_policy_v1`。
5. 单次请求的 `external_evidence_policy_v1` 覆盖必须优先于 bundle 默认值。
6. 非法 `default_mode` 或非法 `external_evidence_policy` 必须被拒绝为无效 bundle，并回退默认 bundle。

验收命令（MUST）：
- `PYTHONPATH=src:tests python3 -m unittest tests.test_runtime_policy_bundle -v`
- `PYTHONPATH=src:tests python3 -m unittest tests.test_thread045_query_gated_runtime -v`
