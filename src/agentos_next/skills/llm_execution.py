from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from agentos_next.llm.backend import LLMBackend, LLMSafetyGate, LLMCallError, LocalMockLLMBackend
from agentos_next.kernel.capabilities import parse_capabilities

from .jsonschema_subset import ValidationError, synthesize_instance, validate_instance
from .package_loader import SkillPackage


class SkillExecutionError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class SkillExecutionOutput:
    output: dict[str, Any]
    backend: str
    prompt: str


def execute_skill_via_llm(
    *,
    pkg: SkillPackage,
    input_obj: Mapping[str, Any],
    backend: Optional[LLMBackend] = None,
    safety: Optional[LLMSafetyGate] = None,
    model_id_override: Optional[str] = None,
    policy_context: Optional[dict[str, Any]] = None,
    stream_callback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> SkillExecutionOutput:
    """Execute a skill package using an LLM backend.

    This is a skeleton "LLM-only" execution path intended for early integration tests.
    """

    backend = backend or LocalMockLLMBackend()
    safety = safety or LLMSafetyGate()

    try:
        validate_instance(dict(input_obj), pkg.artifacts.inputs_schema, path="$.input")
    except ValidationError as e:
        raise SkillExecutionError("E_INPUT_SCHEMA", str(e)) from e

    # Priority: CLI override > skill execution_profile.
    # Remote backends must not inherit the example package's local-only placeholder model_id.
    model_id = _resolve_model_id(
        model_id_override=model_id_override,
        execution_profile=(pkg.artifacts.execution_profile if isinstance(pkg.artifacts.execution_profile, dict) else None),
        backend=backend,
    )

    prompt = build_prompt(pkg=pkg, input_obj=input_obj, policy_context=policy_context)
    input_media = _input_media_from_policy(policy_context)
    try:
        raw_out = _call_complete_json_compat(
            backend=backend,
            prompt=prompt,
            json_schema=_runtime_completion_schema(),
            safety=safety,
            model_id=model_id,
            stream_callback=stream_callback,
            input_media=input_media,
        )
    except LLMCallError as e:
        raise SkillExecutionError(e.error_code, str(e)) from e
    except Exception as e:
        raise SkillExecutionError("E_LLM_CALL", str(e)) from e

    out = _normalize_runtime_completion_output(
        raw_out=raw_out,
        outputs_schema=pkg.artifacts.outputs_schema,
        input_obj=input_obj,
        prompt=prompt,
    )
    try:
        validate_instance(out, pkg.artifacts.outputs_schema, path="$.output")
    except ValidationError as e:
        raise SkillExecutionError("E_OUTPUT_SCHEMA", str(e)) from e

    return SkillExecutionOutput(output=out, backend=backend.__class__.__name__, prompt=prompt)


def _call_complete_json_compat(
    *,
    backend: LLMBackend,
    prompt: str,
    json_schema: Mapping[str, Any],
    safety: LLMSafetyGate,
    model_id: Optional[str],
    stream_callback: Optional[Callable[[dict[str, Any]], None]],
    input_media: list[dict[str, Any]],
) -> Any:
    kwargs: dict[str, Any] = {
        "prompt": prompt,
        "json_schema": dict(json_schema),
        "safety": safety,
        "model_id": model_id,
        "stream_callback": stream_callback,
        "input_media": input_media,
    }
    try:
        sig = inspect.signature(backend.complete_json)
    except Exception:
        sig = None

    if sig is not None:
        params = sig.parameters
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
            return backend.complete_json(**kwargs)
        filtered = {key: value for key, value in kwargs.items() if key in params}
        return backend.complete_json(**filtered)

    try:
        return backend.complete_json(**kwargs)
    except TypeError:
        filtered = {key: value for key, value in kwargs.items() if key not in {"stream_callback", "input_media"}}
        return backend.complete_json(**filtered)


def _resolve_model_id(
    *,
    model_id_override: Optional[str],
    execution_profile: Optional[Mapping[str, Any]],
    backend: Any,
) -> Optional[str]:
    explicit = str(model_id_override or "").strip()
    if explicit:
        return explicit
    if not isinstance(execution_profile, Mapping):
        return None
    candidate = str(execution_profile.get("model_id") or execution_profile.get("model") or "").strip()
    if not candidate:
        return None
    if candidate.lower() == "local_mock" and not isinstance(backend, LocalMockLLMBackend):
        return None
    return candidate


def build_prompt(*, pkg: SkillPackage, input_obj: Mapping[str, Any], policy_context: Optional[dict[str, Any]] = None) -> str:
    inp = json.dumps(dict(input_obj), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    out_contract = _render_output_contract(dict(pkg.artifacts.outputs_schema))
    reasoning_prompt = _reasoning_prompt_from_policy(policy_context)
    execution_prefix = _execution_prefix_from_policy(policy_context) if not reasoning_prompt else ""
    communication_prefix = _communication_prefix_from_policy(policy_context) if not reasoning_prompt else ""
    response_language = _response_language_from_policy(policy_context)
    runtime_actions = _runtime_actions_from_policy(policy_context)
    observation_capsule = _observation_capsule_from_policy(policy_context)
    verified_failure_summary = _verified_failure_summary_from_policy(policy_context)
    active_profile = str((policy_context or {}).get("active_prompt_profile") or "").strip() if isinstance(policy_context, dict) else ""
    memory_pack = _memory_pack_from_policy(
        policy_context,
        execution_prefix=execution_prefix,
        communication_prefix=communication_prefix,
    )
    attachment_context = _attachment_context_from_policy(policy_context)

    parts: list[str] = [
        "Stable Kernel Prefix:",
        "Operate as a task system. Use only grounded observations and allowed runtime actions.",
        "If required evidence is missing, stop and report the blocker instead of inventing support.",
        "",
        "Runtime Rule:",
        "If a tool result contains degraded=true, expectation_mismatch=true, notices, warning, or setup instructions, you MUST tell the user explicitly.",
        "Never silently hide capability gaps, bridge requirements, or degraded execution.",
        "If web.search returns usable results with concrete URLs and web.browse is granted, verifier/executor SHOULD continue with a bounded browse step before blocking solely because search was degraded.",
        "A browse snapshot that only shows page navigation, headers, footers, or other page chrome is not sufficient evidence for a factual answer.",
        "When runtime time facts are present, interpret relative dates like today/tomorrow/yesterday against that anchor instead of asking the user to restate the date.",
    ]

    if runtime_actions:
        parts.extend(
            [
                "",
                "Granted Operators:",
                "Only use operators listed in this section for this turn. If an operator is absent here, treat it as unavailable.",
                *runtime_actions,
            ]
        )

    if reasoning_prompt:
        parts.extend(["", "Compiled Prompt Profile:", reasoning_prompt])
    elif communication_prefix:
        parts.extend(["", "Communication Prefix:", communication_prefix])

    if execution_prefix:
        parts.extend(
            [
                "",
                "Task Block:",
                execution_prefix,
            ]
        )
    elif not reasoning_prompt and not active_profile:
        parts = [
            *parts,
            "",
            f"Skill: {pkg.contract.name} v{pkg.contract.version}",
            "\nLogic:",
            pkg.contract.logic,
        ]

    agent_rules = _agent_rules_from_policy(policy_context)
    if agent_rules and not reasoning_prompt and not execution_prefix and not communication_prefix:
        parts.extend(
            [
                "",
                "Active Agent Rules:",
                "These rules reflect the current agent axioms, reality constraints, and recent execution pressure. They outrank persona/style text when in conflict.",
                *agent_rules,
            ]
        )

    if observation_capsule:
        parts.extend(["", "Observation Capsule:", observation_capsule])

    if verified_failure_summary:
        parts.extend(
            [
                "",
                "Verified Failure Summary:",
                "When this section is present, it is the only allowed source for user-visible root-cause labels, remediation, and blocker explanation boundaries.",
                "Raw observation text MAY support wording only when it does not add new causal claims beyond this summary.",
                verified_failure_summary,
            ]
        )

    if memory_pack:
        parts.extend(["", "Memory Pack:", memory_pack])

    if attachment_context:
        parts.extend(["", "Attachment Context:", attachment_context])

    if response_language:
        parts.extend(
            [
                "",
                "Language Policy:",
                f"All user-visible natural language and send_message.text MUST use: {response_language}",
                "Internal reasoning may stay implementation-defined; user-facing delivery must follow the requested language.",
            ]
        )

    parts.extend(
        [
            "",
            "Runtime Output Rules:",
            "Return one JSON object.",
            "Prefer putting the final skill output under `output`.",
            "Planner and verifier MUST emit top-level worker tasks under `worker_tasks`.",
            "Worker-local executor MAY emit runtime tool actions under `actions`.",
            "If you emit runtime actions, each action MUST use canonical keys `operator_ref` and `arguments`.",
            "Worker tasks MUST use canonical keys `worker_task_id`, `objective`, `depends_on`, `allowed_operator_refs`, `scope_summary`, `completion_contract_ref`, `tool_budget`, and `time_budget_ms`.",
            "Runtime actions MAY include `task_id`/`action_id` and `depends_on` for bounded tool sequencing.",
            "If an action argument depends on an upstream action result, use a structured reference object like "
            "`{\"$from_action\":\"search_docs\",\"path\":[\"results\",0,\"url\"]}` instead of string templates.",
            "If the active role needs an explicit phase verdict, emit `status` as one of continue|done|blocked|need_context.",
            "Only communicator may emit user-visible delivery, and it MUST do so through send_message actions.",
            "Non-communicator phases MUST NOT emit direct user-visible text in `reply`.",
            "If `output` is omitted, the runtime may map top-level `reply` / `reasoning` / `actions` / `worker_tasks` into the final skill output when compatible.",
            "",
            "Input JSON:",
            inp,
            "",
            "Skill Output Validation Contract:",
            out_contract,
            "",
            "Action: Return compact JSON. The final validated skill output must satisfy Skill Output Validation Contract.",
        ]
    )
    return "\n".join(parts)


def _attachment_context_from_policy(policy_context: Optional[dict[str, Any]]) -> str:
    if not isinstance(policy_context, dict):
        return ""
    attachment_context = policy_context.get("attachment_context")
    if not isinstance(attachment_context, Mapping):
        return ""
    lines = [
        f"ATTACHMENTS_PRESENT={bool(attachment_context.get('attachments_present'))}",
        f"ATTACHMENT_USAGE_MODE={str(attachment_context.get('attachment_usage_mode') or 'none').strip()}",
        "REQUIRED_MEDIA_KINDS="
        + (
            "|".join(str(x).strip() for x in (attachment_context.get("required_media_kinds") or []) if str(x).strip())
            or "-"
        ),
        f"TEXT_ONLY_FALLBACK_ALLOWED={bool(attachment_context.get('text_only_fallback_allowed'))}",
        f"MULTIMODAL_CHAIN_SUPPORTED={bool(attachment_context.get('multimodal_chain_supported'))}",
    ]
    block_reason = str(attachment_context.get("multimodal_block_reason") or "").strip()
    if block_reason:
        lines.append(f"MULTIMODAL_BLOCK_REASON={block_reason}")
    selected = [dict(item) for item in (attachment_context.get("selected_attachments") or []) if isinstance(item, Mapping)]
    available = [dict(item) for item in (attachment_context.get("available_attachments") or []) if isinstance(item, Mapping)]
    target = selected or available
    if target:
        lines.append("ATTACHMENTS:")
        for item in target[:6]:
            lines.append(
                "- "
                + " ".join(
                    part
                    for part in [
                        f"id={str(item.get('attachment_id') or '').strip()}",
                        f"kind={str(item.get('media_kind') or '').strip()}",
                        (
                            f"caption={str(item.get('caption') or '').strip()[:120]!r}"
                            if str(item.get("caption") or "").strip()
                            else ""
                        ),
                        f"availability={str(item.get('availability') or '').strip()}",
                        f"download_status={str(item.get('download_status') or '').strip()}",
                    ]
                    if part
                )
            )
    return "\n".join(line for line in lines if line.strip())


def _input_media_from_policy(policy_context: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(policy_context, dict):
        return []
    raw = policy_context.get("selected_attachments")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        local_path = str(item.get("local_path") or "").strip()
        media_kind = str(item.get("media_kind") or "").strip().lower()
        if not local_path or not media_kind:
            continue
        out.append(
            {
                "attachment_id": str(item.get("attachment_id") or "").strip(),
                "media_kind": media_kind,
                "local_path": local_path,
                "mime_type": str(item.get("mime_type") or "").strip() or None,
                "filename": str(item.get("filename") or "").strip() or None,
            }
        )
    return out


def _reasoning_prompt_from_policy(policy_context: Optional[dict[str, Any]]) -> str:
    if not isinstance(policy_context, dict):
        return ""
    explicit = str(policy_context.get("reasoning_prompt") or "").strip()
    if explicit:
        return explicit
    active_profile = str(policy_context.get("active_prompt_profile") or "").strip()
    prompt_profiles = policy_context.get("prompt_profiles")
    if active_profile and isinstance(prompt_profiles, Mapping):
        profile_obj = prompt_profiles.get(active_profile)
        if isinstance(profile_obj, Mapping):
            prompt = str(profile_obj.get("reasoning_prompt") or "").strip()
            if prompt:
                return prompt
    return ""


def _execution_prefix_from_policy(policy_context: Optional[dict[str, Any]]) -> str:
    if not isinstance(policy_context, dict):
        return ""
    execution_prefix = str(
        policy_context.get("execution_prefix")
        or policy_context.get("task_context_envelope")
        or ""
    ).strip()
    if execution_prefix:
        return execution_prefix
    task_envelope = policy_context.get("task_envelope")
    delivery_contract = policy_context.get("delivery_contract")
    if not isinstance(task_envelope, dict):
        return ""
    acceptance = [str(x).strip() for x in (task_envelope.get("acceptance_criteria") or []) if str(x).strip()]
    lines = [
        "PHASE=EXEC",
        f"GOAL={str(task_envelope.get('objective') or '').strip()}",
        f"DELIVERABLE={str(task_envelope.get('deliverable') or '').strip()}",
        f"DONE={str((delivery_contract or {}).get('done_definition') or '').strip()}",
    ]
    if acceptance:
        lines.append("ACCEPT=" + "|".join(acceptance[:4]))
    return "\n".join(lines)


def _communication_prefix_from_policy(policy_context: Optional[dict[str, Any]]) -> str:
    if not isinstance(policy_context, dict):
        return ""
    explicit = str(policy_context.get("communication_prefix") or "").strip()
    if explicit:
        return explicit
    planes = policy_context.get("context_planes")
    if not isinstance(planes, dict):
        return ""
    communication = planes.get("communication_plane")
    if not isinstance(communication, dict):
        return ""
    role_hint = str(communication.get("role_hint") or "").strip()
    style_constraints = [str(x).strip() for x in (communication.get("style_constraints") or []) if str(x).strip()]
    if not role_hint and not style_constraints:
        return ""
    lines = [
        "PHASE=COMM",
        f"ROLE={role_hint or 'assistant'}",
        "STYLE=" + ("|".join(style_constraints[:6]) if style_constraints else "clear|honest|concise"),
        "RULE=comm_must_not_override_exec",
    ]
    return "\n".join(lines)


def _verified_failure_summary_from_policy(policy_context: Optional[dict[str, Any]]) -> str:
    if not isinstance(policy_context, dict):
        return ""
    summary = policy_context.get("verified_failure_summary")
    if not isinstance(summary, Mapping):
        return ""
    facts = [str(x).strip() for x in (summary.get("allowed_user_visible_facts") or []) if str(x).strip()]
    disallowed = [str(x).strip() for x in (summary.get("disallowed_inferences") or []) if str(x).strip()]
    if not facts and not disallowed:
        return ""
    lines = [
        f"PHASE_OUTCOME={str(summary.get('phase_outcome') or '').strip()}",
        f"PRIMARY_ERROR_CODE={str(summary.get('primary_error_code') or '').strip()}",
        f"FAILED_PHASE={str(summary.get('failed_phase') or '').strip()}",
        f"REASON_CLASS={str(summary.get('reason_class') or '').strip()}",
        f"TEMPLATE_KEY={str(summary.get('template_key') or '').strip()}",
    ]
    objective = str(summary.get("objective") or "").strip()
    if objective:
        lines.append(f"OBJECTIVE={objective}")
    if facts:
        lines.append("ALLOWED_USER_VISIBLE_FACTS:")
        lines.extend(f"- {item}" for item in facts)
    if disallowed:
        lines.append("DISALLOWED_INFERENCES:")
        lines.extend(f"- {item}" for item in disallowed)
    next_step_hint = str(summary.get("next_step_hint") or "").strip()
    if next_step_hint:
        lines.append(f"NEXT_STEP_HINT={next_step_hint}")
    return "\n".join(line for line in lines if line.strip())


def _response_language_from_policy(policy_context: Optional[dict[str, Any]]) -> str:
    if not isinstance(policy_context, dict):
        return ""
    explicit = str(policy_context.get("response_language") or "").strip()
    if explicit:
        return explicit
    planes = policy_context.get("context_planes")
    if isinstance(planes, dict):
        communication = planes.get("communication_plane")
        if isinstance(communication, dict):
            value = str(communication.get("response_language") or "").strip()
            if value:
                return value
    return ""


def _memory_pack_from_policy(
    policy_context: Optional[dict[str, Any]],
    *,
    execution_prefix: str,
    communication_prefix: str,
) -> str:
    del execution_prefix
    del communication_prefix
    if not isinstance(policy_context, dict):
        return ""
    mem = policy_context.get("memory_context")
    if not isinstance(mem, dict):
        return ""
    lines: list[str] = []
    l0_continuity = mem.get("l0_continuity")
    if isinstance(l0_continuity, dict):
        bits = []
        for key in (
            "workspace_id",
            "conversation_id",
            "active_project_id",
            "last_delivery_state",
            "last_delivery_summary",
            "last_user_query",
            "expected_next_user_act",
        ):
            value = str(l0_continuity.get(key) or "").strip()
            if value:
                bits.append(f"{key}={value}")
        blocker = l0_continuity.get("blocker")
        if isinstance(blocker, dict):
            summary = str(blocker.get("summary") or blocker.get("reason") or "").strip()
            if summary:
                bits.append(f"blocker={summary}")
        if bits:
            lines.append("L0 CONTINUITY")
            lines.extend(f"- {bit}" for bit in bits)
    l1_query = mem.get("l1_query")
    if isinstance(l1_query, dict):
        bits = []
        query = str(l1_query.get("query") or "").strip()
        intent = str(l1_query.get("intent") or "").strip()
        if query:
            bits.append(f"query={query}")
        if intent:
            bits.append(f"intent={intent}")
        limit = l1_query.get("limit")
        if limit is not None:
            bits.append(f"limit={limit}")
        if bits:
            lines.append("L1 QUERY")
            lines.extend(f"- {bit}" for bit in bits)
    l2_hits = mem.get("l2_hits")
    if isinstance(l2_hits, list) and l2_hits:
        rendered = []
        for item in l2_hits[:6]:
            if not isinstance(item, dict):
                continue
            summary = str(item.get("summary") or "").strip()
            kind = str(item.get("kind") or "").strip()
            ref = str(item.get("evidence_ref") or "").strip()
            freshness = str(item.get("freshness") or "").strip()
            if summary:
                suffix = ", ".join(bit for bit in (kind, freshness, ref) if bit)
                rendered.append(f"- {summary}" + (f" ({suffix})" if suffix else ""))
        if rendered:
            lines.append("L2 HITS")
            lines.extend(rendered)
    conflicts = mem.get("conflicts")
    if isinstance(conflicts, list) and conflicts:
        rendered = []
        for item in conflicts[:4]:
            if not isinstance(item, dict):
                continue
            key = str(item.get("memory_key") or "").strip()
            summaries = [str(x).strip() for x in (item.get("summaries") or []) if str(x).strip()]
            if key or summaries:
                rendered.append(f"- {key or 'conflict'}: {' | '.join(summaries[:3])}")
        if rendered:
            lines.append("CONFLICTS")
            lines.extend(rendered)
    retrieval_ref = str(mem.get("retrieval_ref") or "").strip()
    if retrieval_ref:
        lines.append(f"RETRIEVAL_REF={retrieval_ref}")
    return "\n".join(lines).strip()


def _observation_capsule_from_policy(policy_context: Optional[dict[str, Any]]) -> str:
    if not isinstance(policy_context, dict):
        return ""
    return str(policy_context.get("execution_observation_capsule") or "").strip()


def _runtime_completion_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "output": {"type": "object"},
            "status": {"type": "string"},
            "reply": {"type": "string"},
            "reasoning": {"type": "string"},
            "worker_tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "worker_task_id": {"type": "string"},
                        "objective": {"type": "string"},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                        "allowed_operator_refs": {"type": "array", "items": {"type": "string"}},
                        "scope_summary": {"type": "string"},
                        "completion_contract_ref": {"type": "string"},
                        "tool_budget": {"type": "object"},
                        "time_budget_ms": {"type": "integer"},
                    },
                    "additionalProperties": True,
                },
            },
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "operator_ref": {"type": "string"},
                        "arguments": {"type": "object"},
                    },
                    "additionalProperties": True,
                },
            },
        },
        "additionalProperties": True,
    }


def _normalize_runtime_completion_output(
    *,
    raw_out: Mapping[str, Any],
    outputs_schema: Mapping[str, Any],
    input_obj: Mapping[str, Any],
    prompt: str,
) -> dict[str, Any]:
    runtime_output = _normalize_runtime_completion_candidate(
        raw_out=raw_out,
        input_obj=input_obj,
        prompt=prompt,
    )
    return _project_runtime_output_to_validation_schema(
        runtime_output=runtime_output,
        outputs_schema=outputs_schema,
        input_obj=input_obj,
        prompt=prompt,
    )


def _extract_prompt_profile(prompt: str) -> str:
    for marker in ("PROMPT_PROFILE=", "PROFILE_ID="):
        idx = prompt.find(marker)
        if idx < 0:
            continue
        tail = prompt[idx + len(marker) :].splitlines()[0].strip()
        if tail:
            return tail
    return ""


def _extract_goal_text(prompt: str, input_obj: Mapping[str, Any]) -> str:
    for marker in ("GOAL=", "TASK_FRAMING=", "RETRIEVAL_QUERY="):
        idx = prompt.find(marker)
        if idx >= 0:
            tail = prompt[idx + len(marker) :].splitlines()[0].strip()
            if tail and tail != "-":
                return tail
    request = str(input_obj.get("request") or "").strip()
    return request


def _default_mock_message_text(prompt: str, input_obj: Mapping[str, Any]) -> str:
    goal = _extract_goal_text(prompt, input_obj)
    response_language = _extract_response_language(prompt)
    if response_language.lower().startswith("zh"):
        return f"[mock] {goal}" if goal else "[mock] 好的"
    return f"[mock] {goal}" if goal else "[mock] ok"


def _extract_response_language(prompt: str) -> str:
    marker = "RESPONSE_LANGUAGE="
    idx = prompt.find(marker)
    if idx < 0:
        return ""
    tail = prompt[idx + len(marker) :].splitlines()[0].strip()
    return "" if tail.lower() == "auto" else tail


def _default_mock_actions_for_profile(prompt: str, profile_id: str) -> list[dict[str, Any]]:
    prompt_l = prompt.lower()
    if profile_id == "communicator":
        return [
            {
                "operator_ref": "builtin://channel.send_message",
                "arguments": {
                    "text": _default_mock_message_text(prompt, {}),
                    "audience": "user",
                    "update_preference": "prefer_update",
                },
            }
        ]
    if profile_id in {"planner", "executor"} and (
        "project_work" in prompt_l
        or "inspect workspace artifacts" in prompt_l
        or "分析这个项目" in prompt
        or "架构建议" in prompt
    ):
        return [
            {
                "task_id": "inspect_workspace",
                "operator_ref": "builtin://fs.list",
                "arguments": {"path": "."},
            },
            {
                "task_id": "discover_key_files",
                "operator_ref": "builtin://shell.exec",
                "arguments": {
                    "command": "find . -maxdepth 2 \\( -name README.md -o -name README -o -name pyproject.toml -o -name package.json -o -name Makefile \\) | sort",
                    "cwd": ".",
                },
                "depends_on": ["inspect_workspace"],
            },
        ]
    return []


def _default_mock_worker_tasks_for_profile(prompt: str, profile_id: str) -> list[dict[str, Any]]:
    prompt_l = prompt.lower()
    if profile_id not in {"planner", "verifier_replanner"}:
        return []
    if (
        "project_work" in prompt_l
        or "inspect workspace artifacts" in prompt_l
        or "分析这个项目" in prompt
        or "架构建议" in prompt
    ):
        return [
            {
                "worker_task_id": "inspect_workspace_worker",
                "objective": "Inspect the workspace and collect the key project files needed to answer the user.",
                "depends_on": [],
                "allowed_operator_refs": ["builtin://fs.list", "builtin://shell.exec", "builtin://fs.read"],
                "scope_summary": "Read-only workspace inspection only.",
                "completion_contract_ref": "worker_contract:inspect_workspace",
                "tool_budget": {
                    "max_calls": 4,
                    "max_parallel_calls": 2,
                    "retry_read_only_tools": True,
                },
                "time_budget_ms": 12000,
            }
        ]
    return []


def _synthesized_runtime_completion_output(*, input_obj: Mapping[str, Any], prompt: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    profile_id = _extract_prompt_profile(prompt)
    if profile_id:
        out["status"] = "done"
    if profile_id == "communicator":
        out["actions"] = _default_mock_actions_for_profile(prompt, profile_id)
    elif profile_id == "executor":
        default_actions = _default_mock_actions_for_profile(prompt, profile_id)
        if default_actions:
            out["actions"] = default_actions
            out["status"] = "continue"
    elif profile_id in {"planner", "verifier_replanner"}:
        default_worker_tasks = _default_mock_worker_tasks_for_profile(prompt, profile_id)
        if default_worker_tasks:
            out["worker_tasks"] = default_worker_tasks
            out["status"] = "continue"
    if profile_id in {"communicator", ""}:
        out["reply"] = _default_mock_message_text(prompt, input_obj)
    return out


def _synthesized_skill_output(*, outputs_schema: Mapping[str, Any], input_obj: Mapping[str, Any], prompt: str) -> dict[str, Any]:
    try:
        base = synthesize_instance(outputs_schema)
    except Exception:
        base = {}
    out = dict(base) if isinstance(base, dict) else {}
    runtime_defaults = _synthesized_runtime_completion_output(input_obj=input_obj, prompt=prompt)
    for key, value in runtime_defaults.items():
        if key == "reply":
            current = out.get("reply")
            if _schema_accepts_field(outputs_schema, "reply") and (not isinstance(current, str) or not current.strip()):
                out["reply"] = value
            continue
        if key == "actions":
            current = out.get("actions")
            if _schema_accepts_field(outputs_schema, "actions") and (not isinstance(current, list) or not current):
                out["actions"] = value
            continue
        if key == "worker_tasks":
            current = out.get("worker_tasks")
            if _schema_accepts_field(outputs_schema, "worker_tasks") and (not isinstance(current, list) or not current):
                out["worker_tasks"] = value
            continue
        if _schema_accepts_field(outputs_schema, key):
            out.setdefault(key, value)
    return out


def _normalize_runtime_completion_candidate(
    *,
    raw_out: Mapping[str, Any],
    input_obj: Mapping[str, Any],
    prompt: str,
) -> dict[str, Any]:
    runtime_output = _synthesized_runtime_completion_output(input_obj=input_obj, prompt=prompt)
    if not isinstance(raw_out, Mapping):
        return runtime_output

    profile_id = _extract_prompt_profile(prompt)
    explicit_output = raw_out.get("output")
    if isinstance(explicit_output, Mapping):
        runtime_output.update(dict(explicit_output))

    for field in ("status", "reply", "reasoning"):
        value = raw_out.get(field)
        if not isinstance(value, str):
            continue
        if field == "reply" and profile_id not in {"", "communicator"}:
            continue
        runtime_output[field] = value

    raw_actions = raw_out.get("actions")
    if isinstance(raw_actions, list):
        runtime_output["actions"] = _normalize_actions_for_output_schema(raw_actions, outputs_schema={})
    raw_worker_tasks = raw_out.get("worker_tasks")
    if isinstance(raw_worker_tasks, list):
        runtime_output["worker_tasks"] = _normalize_worker_tasks_for_output_schema(raw_worker_tasks)

    if not any(k in raw_out for k in ("output", "status", "reply", "reasoning", "actions", "worker_tasks")):
        runtime_output.update(dict(raw_out))

    if profile_id not in {"", "communicator"}:
        runtime_output.pop("reply", None)
    return runtime_output


def _project_runtime_output_to_validation_schema(
    *,
    runtime_output: Mapping[str, Any],
    outputs_schema: Mapping[str, Any],
    input_obj: Mapping[str, Any],
    prompt: str,
) -> dict[str, Any]:
    synthesized = _synthesized_skill_output(outputs_schema=outputs_schema, input_obj=input_obj, prompt=prompt)
    projected = dict(synthesized)
    for key, value in dict(runtime_output or {}).items():
        if not _schema_accepts_field(outputs_schema, key):
            continue
        projected[key] = value
    profile_id = _extract_prompt_profile(prompt)
    if profile_id not in {"", "communicator"}:
        projected.pop("reply", None)
    return projected


def _schema_accepts_field(outputs_schema: Mapping[str, Any], field: str) -> bool:
    if not outputs_schema:
        return True
    props = outputs_schema.get("properties")
    if isinstance(props, Mapping) and field in props:
        return True
    additional = outputs_schema.get("additionalProperties")
    return additional is not False


def _normalize_actions_for_output_schema(
    actions: list[Any],
    *,
    outputs_schema: Mapping[str, Any],
) -> list[dict[str, Any]]:
    action_shape = _output_action_shape(outputs_schema)
    normalized: list[dict[str, Any]] = []
    for item in actions:
        if not isinstance(item, Mapping):
            continue
        operator_ref = str(item.get("operator_ref") or "").strip()
        arguments_raw = item.get("arguments")
        arguments = dict(arguments_raw) if isinstance(arguments_raw, Mapping) else {}
        action_id = str(item.get("action_id") or "").strip()
        depends_on_raw = item.get("depends_on") or []
        depends_on = [str(x).strip() for x in depends_on_raw if str(x).strip()] if isinstance(depends_on_raw, list) else []
        kind = str(item.get("kind") or "").strip()
        if action_shape == "legacy":
            action_obj: dict[str, Any] = {"operator_ref": operator_ref, "arguments": arguments}
            if action_id:
                action_obj["action_id"] = action_id
            if depends_on:
                action_obj["depends_on"] = depends_on
            if kind:
                action_obj["kind"] = kind
            normalized.append(action_obj)
        else:
            action_obj = {"operator_ref": operator_ref, "arguments": arguments}
            if action_id:
                action_obj["action_id"] = action_id
            if depends_on:
                action_obj["depends_on"] = depends_on
            if kind:
                action_obj["kind"] = kind
            normalized.append(action_obj)
    return normalized


def _normalize_worker_tasks_for_output_schema(tasks: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, item in enumerate(tasks, start=1):
        if not isinstance(item, Mapping):
            continue
        worker_task_id = str(item.get("worker_task_id") or "").strip() or f"worker_task_{idx}"
        if worker_task_id in seen_ids:
            worker_task_id = f"{worker_task_id}_{idx}"
        seen_ids.add(worker_task_id)
        depends_on_raw = item.get("depends_on") or []
        allowed_raw = item.get("allowed_operator_refs") or []
        tool_budget_raw = item.get("tool_budget") or {}
        task_obj = {
            "worker_task_id": worker_task_id,
            "objective": str(item.get("objective") or "").strip(),
            "depends_on": [str(x).strip() for x in depends_on_raw if str(x).strip()] if isinstance(depends_on_raw, list) else [],
            "allowed_operator_refs": [str(x).strip() for x in allowed_raw if str(x).strip()] if isinstance(allowed_raw, list) else [],
            "scope_summary": str(item.get("scope_summary") or "").strip(),
            "completion_contract_ref": str(item.get("completion_contract_ref") or "").strip(),
            "tool_budget": {
                "max_calls": max(1, int((tool_budget_raw or {}).get("max_calls") or 1)),
                "max_parallel_calls": max(1, int((tool_budget_raw or {}).get("max_parallel_calls") or 1)),
                "retry_read_only_tools": bool((tool_budget_raw or {}).get("retry_read_only_tools")),
            },
            "time_budget_ms": max(0, int(item.get("time_budget_ms") or 0)),
        }
        normalized.append(task_obj)
    return normalized


def _output_action_shape(outputs_schema: Mapping[str, Any]) -> str:
    props = outputs_schema.get("properties")
    if not isinstance(props, Mapping):
        return "canonical"
    actions = props.get("actions")
    if not isinstance(actions, Mapping):
        return "canonical"
    items = actions.get("items")
    if not isinstance(items, Mapping):
        return "canonical"
    item_props = items.get("properties")
    if not isinstance(item_props, Mapping):
        return "canonical"
    if "operator_ref" in item_props or "arguments" in item_props:
        return "canonical"
    if "skill_ref" in item_props or "input" in item_props:
        return "legacy"
    return "canonical"


def _render_output_contract(schema: Mapping[str, Any]) -> str:
    if not isinstance(schema, Mapping):
        return "{}"
    if str(schema.get("type") or "") != "object":
        return json.dumps(dict(schema), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    required = {
        str(x).strip() for x in (schema.get("required") or []) if str(x).strip()
    }
    props = schema.get("properties") or {}
    if not isinstance(props, Mapping):
        return json.dumps(dict(schema), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    lines = ["type: object"]
    if required:
        lines.append("required: " + ", ".join(sorted(required)))
    lines.append("fields:")
    for name, raw in props.items():
        if not isinstance(name, str) or not isinstance(raw, Mapping):
            continue
        typ = str(raw.get("type") or "any").strip() or "any"
        bits = [typ]
        enum = raw.get("enum")
        if isinstance(enum, list) and enum:
            vals = [str(x) for x in enum[:6]]
            bits.append("enum=" + "|".join(vals))
        if "minLength" in raw:
            bits.append(f"minLength={raw.get('minLength')}")
        if "maxLength" in raw:
            bits.append(f"maxLength={raw.get('maxLength')}")
        desc = str(raw.get("description") or "").strip()
        line = f"- {name}: " + ", ".join(bits)
        if desc:
            line += f" // {desc}"
        lines.append(line)
    if not props:
        lines.append("- none")
    return "\n".join(lines)


def _streaming_reply_expected(policy_context: Optional[dict[str, Any]]) -> bool:
    if not isinstance(policy_context, dict):
        return False
    if callable(policy_context.get("llm_stream_callback")):
        return True
    if policy_context.get("telegram_stream_session") is not None:
        return True
    return False


def _runtime_actions_from_policy(policy_context: Optional[dict[str, Any]]) -> list[str]:
    if not isinstance(policy_context, dict):
        return []
    parsed = parse_capabilities(policy_context)
    if not parsed.ok:
        return []
    active_profile = str(policy_context.get("active_prompt_profile") or "").strip()
    if active_profile == "communicator":
        return ["- builtin://channel.send_message(text, audience?, metadata?, message_key?, delivery_stage?, update_preference?)"]

    if active_profile in {"intent_router", "verifier_replanner"}:
        return []

    lines: list[str] = []
    if "fs_read" in parsed.names:
        lines.extend(["- builtin://fs.read(path)", "- builtin://fs.list(path)"])
    if "fs_write" in parsed.names:
        lines.append("- builtin://fs.write(path, content)")
    if "shell_exec" in parsed.names:
        lines.append("- builtin://shell.exec(command, cwd)")
    if "memory_write" in parsed.names:
        lines.append("- builtin://memory.write(record)")
    if "memory_search" in parsed.names:
        lines.append("- builtin://memory.search(query, intent, scope, kinds, limit, include_stale?, include_deleted?)")
    if "memory_compact" in parsed.names:
        lines.append("- builtin://memory.compact(memory_key, scope, winner)")
    if "memory_delete" in parsed.names:
        lines.append("- builtin://memory.delete(record_ids)")
    if "channel_send" in parsed.names and not active_profile:
        lines.append("- builtin://channel.send_message(text, audience?, metadata?)")
    if "time_read" in parsed.names:
        lines.append("- builtin://time.now()")
    if "web_search" in parsed.names:
        lines.append("- builtin://web.search(query, limit?)")
    if "web_browse" in parsed.names:
        lines.append("- builtin://web.browse(url)")
    if "research_run" in parsed.names:
        lines.append("- builtin://research.run(objective, depth?, report_format?, min_sources?)")
    if "scheduler_write" in parsed.names:
        lines.extend(["- builtin://scheduler.at(...)", "- builtin://scheduler.cron(...)"])
    if "fs_read" in parsed.names:
        lines.append("- builtin://creator.plan(intent, registry_root?, max_steps?)")
    return lines


def _agent_rules_from_policy(policy_context: Optional[dict[str, Any]]) -> list[str]:
    if not isinstance(policy_context, dict):
        return []
    lines: list[str] = []
    profile = policy_context.get("agent_profile")
    if isinstance(profile, dict):
        axioms = profile.get("axioms") or []
        if isinstance(axioms, list):
            normalized_axioms = []
            for ax in axioms:
                if not isinstance(ax, dict):
                    continue
                ax_id = str(ax.get("id") or "").strip()
                statement = str(ax.get("statement") or "").strip()
                try:
                    priority = int(ax.get("priority"))
                except Exception:
                    priority = 999
                if ax_id and statement:
                    normalized_axioms.append((priority, ax_id, statement))
            for _priority, ax_id, statement in sorted(normalized_axioms, key=lambda item: (item[0], item[1])):
                lines.append(f"- axiom {ax_id}: {statement}")
        constraints = profile.get("reality_constraints") or []
        if isinstance(constraints, list):
            for rc in constraints:
                if not isinstance(rc, dict):
                    continue
                rc_id = str(rc.get("id") or "").strip()
                statement = str(rc.get("statement") or "").strip()
                if rc_id and statement:
                    lines.append(f"- constraint {rc_id}: {statement}")
    planes = policy_context.get("context_planes")
    if isinstance(planes, dict):
        retrospective = planes.get("retrospective_plane")
        if isinstance(retrospective, dict):
            recent_failures = retrospective.get("recent_failures") or []
            if isinstance(recent_failures, list):
                trimmed = [str(x).strip() for x in recent_failures if str(x).strip()][:3]
                if trimmed:
                    lines.append("- recent_failures: avoid repeating these failed paths without new evidence")
                    for item in trimmed:
                        lines.append(f"  {item}")
    return lines
