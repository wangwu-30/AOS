from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


ExecutionLane = Literal[
    "fast_chat",
    "standard_task",
    "deep_task",
    "research_task",
    "skill_exec",
]

EffectClass = Literal[
    "read_only",
    "workspace_write",
    "external_effect",
    "user_visible_delivery",
]

VerificationMode = Literal["final_only", "milestone"]


READ_ONLY_OPERATOR_PREFIXES = (
    "builtin://fs.read",
    "builtin://fs.list",
    "builtin://web.search",
    "builtin://web.browse",
    "builtin://memory.search",
    "builtin://time.",
)

WORKSPACE_WRITE_PREFIXES = (
    "builtin://fs.write",
    "builtin://memory.write",
    "builtin://memory.delete",
    "builtin://memory.compact",
)

EXTERNAL_EFFECT_PREFIXES = (
    "builtin://shell.exec",
    "builtin://scheduler.",
)

USER_VISIBLE_DELIVERY_PREFIXES = (
    "builtin://channel.send_message",
)


@dataclass(frozen=True)
class TokenBudget:
    max_total_tokens: int = 0
    reserve_tokens: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "max_total_tokens": max(0, int(self.max_total_tokens or 0)),
            "reserve_tokens": max(0, int(self.reserve_tokens or 0)),
        }


@dataclass(frozen=True)
class StopPolicy:
    deadline_ms: int = 0
    no_progress_window: int = 3
    max_repeated_action_fingerprint_hits: int = 2
    verification_mode: VerificationMode = "final_only"
    continue_until_terminal: bool = True

    def to_json(self) -> dict[str, Any]:
        return {
            "deadline_ms": max(0, int(self.deadline_ms or 0)),
            "no_progress_window": max(1, int(self.no_progress_window or 1)),
            "max_repeated_action_fingerprint_hits": max(1, int(self.max_repeated_action_fingerprint_hits or 1)),
            "verification_mode": str(self.verification_mode or "final_only"),
            "continue_until_terminal": bool(self.continue_until_terminal),
        }


@dataclass(frozen=True)
class ExecutionLaneProfile:
    lane: ExecutionLane
    reasoning_profile_ref: str
    model_pool_ref: str
    tool_parallelism_cap: int
    max_reasoning_turns: int
    on_lane_insufficient: str
    verification_mode: str


DEFAULT_EXECUTION_LANE_CONFIGS: dict[ExecutionLane, dict[str, Any]] = {
    "fast_chat": {
        "reasoning_profile_ref": "lane.fast_chat",
        "model_pool_ref": "pool.fast",
        "tool_parallelism_cap": 1,
        "max_reasoning_turns": 8,
        "on_lane_insufficient": "controller_replan",
        "verification_mode": "final_only",
    },
    "standard_task": {
        "reasoning_profile_ref": "lane.standard_task",
        "model_pool_ref": "pool.standard",
        "tool_parallelism_cap": 1,
        "max_reasoning_turns": 16,
        "on_lane_insufficient": "controller_replan",
        "verification_mode": "final_only",
    },
    "deep_task": {
        "reasoning_profile_ref": "lane.deep_task",
        "model_pool_ref": "pool.deep",
        "tool_parallelism_cap": 2,
        "max_reasoning_turns": 32,
        "on_lane_insufficient": "controller_replan",
        "verification_mode": "milestone",
    },
    "research_task": {
        "reasoning_profile_ref": "lane.research_task",
        "model_pool_ref": "pool.research",
        "tool_parallelism_cap": 2,
        "max_reasoning_turns": 48,
        "on_lane_insufficient": "controller_replan",
        "verification_mode": "milestone",
    },
    "skill_exec": {
        "reasoning_profile_ref": "lane.skill_exec",
        "model_pool_ref": "pool.skill",
        "tool_parallelism_cap": 1,
        "max_reasoning_turns": 24,
        "on_lane_insufficient": "controller_replan",
        "verification_mode": "final_only",
    },
}


def normalize_execution_lane(value: Any) -> ExecutionLane:
    raw = str(value or "").strip().lower()
    if raw in DEFAULT_EXECUTION_LANE_CONFIGS:
        return raw  # type: ignore[return-value]
    return "standard_task"


def resolve_execution_lane_config(
    *,
    lane: Any,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = normalize_execution_lane(lane)
    config = dict(DEFAULT_EXECUTION_LANE_CONFIGS[normalized])
    if isinstance(overrides, dict):
        config.update({str(k): v for k, v in overrides.items()})
    config["execution_lane"] = normalized
    return config


def build_default_token_budget(*, max_total_tokens: int = 0, reserve_tokens: int = 0) -> dict[str, Any]:
    return TokenBudget(
        max_total_tokens=max(0, int(max_total_tokens or 0)),
        reserve_tokens=max(0, int(reserve_tokens or 0)),
    ).to_json()


def build_default_stop_policy(
    *,
    deadline_ms: int = 0,
    no_progress_window: int = 3,
    max_repeated_action_fingerprint_hits: int = 2,
    verification_mode: VerificationMode = "final_only",
) -> dict[str, Any]:
    return StopPolicy(
        deadline_ms=max(0, int(deadline_ms or 0)),
        no_progress_window=max(1, int(no_progress_window or 1)),
        max_repeated_action_fingerprint_hits=max(1, int(max_repeated_action_fingerprint_hits or 1)),
        verification_mode=verification_mode,
        continue_until_terminal=True,
    ).to_json()


def execution_lane_policy(lane: Any) -> ExecutionLaneProfile:
    config = resolve_execution_lane_config(lane=lane)
    return ExecutionLaneProfile(
        lane=normalize_execution_lane(config.get("execution_lane")),
        reasoning_profile_ref=str(config.get("reasoning_profile_ref") or ""),
        model_pool_ref=str(config.get("model_pool_ref") or ""),
        tool_parallelism_cap=max(1, int(config.get("tool_parallelism_cap") or 1)),
        max_reasoning_turns=max(1, int(config.get("max_reasoning_turns") or 1)),
        on_lane_insufficient=str(config.get("on_lane_insufficient") or "controller_replan"),
        verification_mode=str(config.get("verification_mode") or "final_only"),
    )


def execution_lane_policy_payload(lane: Any) -> dict[str, Any]:
    profile = execution_lane_policy(lane)
    return {
        "lane": profile.lane,
        "reasoning_profile_ref": profile.reasoning_profile_ref,
        "model_pool_ref": profile.model_pool_ref,
        "tool_parallelism_cap": int(profile.tool_parallelism_cap),
        "max_reasoning_turns": int(profile.max_reasoning_turns),
        "on_lane_insufficient": profile.on_lane_insufficient,
        "verification_mode": profile.verification_mode,
    }


def default_token_budget_for_lane(lane: Any) -> dict[str, Any]:
    normalized = normalize_execution_lane(lane)
    defaults = {
        "fast_chat": (12000, 1000),
        "standard_task": (24000, 2000),
        "deep_task": (48000, 4000),
        "research_task": (64000, 6000),
        "skill_exec": (32000, 2000),
    }
    max_total_tokens, reserve_tokens = defaults.get(normalized, defaults["standard_task"])
    return build_default_token_budget(
        max_total_tokens=max_total_tokens,
        reserve_tokens=reserve_tokens,
    )


def default_stop_policy_for_lane(
    lane: Any,
    *,
    deadline_ms: int = 0,
) -> dict[str, Any]:
    normalized = normalize_execution_lane(lane)
    verification_mode = str(DEFAULT_EXECUTION_LANE_CONFIGS[normalized].get("verification_mode") or "final_only")
    no_progress_defaults = {
        "fast_chat": 2,
        "standard_task": 3,
        "deep_task": 4,
        "research_task": 5,
        "skill_exec": 4,
    }
    repeated_action_defaults = {
        "fast_chat": 2,
        "standard_task": 2,
        "deep_task": 3,
        "research_task": 3,
        "skill_exec": 2,
    }
    return build_default_stop_policy(
        deadline_ms=max(0, int(deadline_ms or 0)),
        no_progress_window=no_progress_defaults.get(normalized, 3),
        max_repeated_action_fingerprint_hits=repeated_action_defaults.get(normalized, 2),
        verification_mode=verification_mode,  # type: ignore[arg-type]
    )


def is_read_only_operator(operator_ref: str) -> bool:
    ref = str(operator_ref or "").strip()
    return any(ref.startswith(prefix) for prefix in READ_ONLY_OPERATOR_PREFIXES)


def infer_effect_class(*, allowed_operator_refs: list[str] | tuple[str, ...] | set[str] | None) -> EffectClass:
    refs = [str(item).strip() for item in (allowed_operator_refs or []) if str(item).strip()]
    if not refs:
        return "read_only"
    if any(any(ref.startswith(prefix) for prefix in USER_VISIBLE_DELIVERY_PREFIXES) for ref in refs):
        return "user_visible_delivery"
    if any(any(ref.startswith(prefix) for prefix in EXTERNAL_EFFECT_PREFIXES) for ref in refs):
        return "external_effect"
    if any(any(ref.startswith(prefix) for prefix in WORKSPACE_WRITE_PREFIXES) for ref in refs):
        return "workspace_write"
    if all(is_read_only_operator(ref) for ref in refs):
        return "read_only"
    return "external_effect"


def clamp_tool_budget_for_lane(
    *,
    tool_budget: dict[str, Any] | None,
    lane: Any,
) -> dict[str, Any]:
    profile = execution_lane_policy(lane)
    budget = dict(tool_budget or {})
    budget["max_calls"] = max(1, int(budget.get("max_calls") or 1))
    budget["max_parallel_calls"] = min(
        max(1, int(budget.get("max_parallel_calls") or 1)),
        int(profile.tool_parallelism_cap),
    )
    budget["retry_read_only_tools"] = bool(budget.get("retry_read_only_tools"))
    return budget


def next_execution_lane(
    lane: Any,
    *,
    prefer_research: bool = False,
) -> ExecutionLane | None:
    normalized = normalize_execution_lane(lane)
    if normalized == "fast_chat":
        return "standard_task"
    if normalized == "standard_task":
        return "research_task" if prefer_research else "deep_task"
    if normalized == "deep_task":
        return "research_task" if prefer_research else None
    return None


def classify_execution_lane(
    *,
    interaction_mode: str,
    solution_query: dict[str, Any] | None = None,
    task_requirements: dict[str, Any] | None = None,
    preferred_operator_refs: list[str] | None = None,
    worker_task_count: int = 0,
) -> ExecutionLane:
    mode = str(interaction_mode or "task").strip().lower()
    solution = dict(solution_query or {})
    requirements = dict(task_requirements or {})
    preferred = [str(item).strip() for item in (preferred_operator_refs or []) if str(item).strip()]

    if any(ref.startswith("registry://") for ref in preferred) or solution.get("approach_strategy") == "local_skill_first":
        return "skill_exec"
    if bool(requirements.get("research_required")) or bool(requirements.get("citation_required")):
        return "research_task"
    if bool(requirements.get("requires_workspace_observation")) or worker_task_count > 1:
        return "deep_task"
    if mode in {"chat", "status", "confirm"}:
        return "fast_chat"
    return "standard_task"
