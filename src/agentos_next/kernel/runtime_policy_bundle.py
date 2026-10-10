from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_EXECUTION_MODES = {"cost_saver", "balanced", "quality_first", "chat_first"}
_RISK_TOLERANCE = {"low", "balanced", "high"}
_DATA_LEVELS = {"L0", "L1", "L2"}
_STORAGE_BEHAVIORS = {"process_only", "local_only", "local_or_sync"}
_EXTERNAL_EVIDENCE_DEFAULTS = {
    "search_rounds_max": 2,
    "browse_candidates_per_search_max": 3,
    "total_browse_steps_max": 4,
}


def _safe_segment(value: str, *, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    if re.fullmatch(r"[A-Za-z0-9._-]{1,200}", raw):
        return raw
    return fallback


def _normalize_text_list(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if value:
            out.append(value)
    return out


def _normalize_hour_list(items: Any, *, field: str) -> tuple[list[int] | None, str | None]:
    if items is None:
        return [], None
    if not isinstance(items, list):
        return None, f"{field} must be an array"
    hours: list[int] = []
    for item in items:
        try:
            hour = int(item)
        except Exception:
            return None, f"{field} must contain integers"
        if hour < 0 or hour > 23:
            return None, f"{field} entries must be within [0, 23]"
        hours.append(hour)
    return sorted(dict.fromkeys(hours)), None


def _normalize_storage_policy(raw: Any) -> tuple[dict[str, str] | None, str | None]:
    defaults = {"L0": "process_only", "L1": "local_only", "L2": "local_or_sync"}
    if raw is None:
        return defaults, None
    if not isinstance(raw, dict):
        return None, "data_sensitivity_policy.storage_policy must be an object"
    normalized = dict(defaults)
    for level, behavior in raw.items():
        key = str(level or "").strip()
        value = str(behavior or "").strip()
        if key not in _DATA_LEVELS:
            return None, "data_sensitivity_policy.storage_policy keys must be one of L0/L1/L2"
        if value not in _STORAGE_BEHAVIORS:
            return None, "data_sensitivity_policy.storage_policy values must be process_only/local_only/local_or_sync"
        normalized[key] = value
    return normalized, None


def _normalize_positive_int(
    value: Any,
    *,
    field: str,
    default: int,
    minimum: int,
    maximum: int,
) -> tuple[int | None, str | None]:
    if value is None:
        return default, None
    try:
        parsed = int(value)
    except Exception:
        return None, f"{field} must be an integer"
    if parsed < minimum or parsed > maximum:
        return None, f"{field} must be within [{minimum}, {maximum}]"
    return parsed, None


def _normalize_external_evidence_policy(raw: Any) -> tuple[dict[str, int] | None, str | None]:
    if raw is None:
        return dict(_EXTERNAL_EVIDENCE_DEFAULTS), None
    if not isinstance(raw, dict):
        return None, "external_evidence_policy must be an object"
    search_rounds_max, err = _normalize_positive_int(
        raw.get("search_rounds_max"),
        field="external_evidence_policy.search_rounds_max",
        default=_EXTERNAL_EVIDENCE_DEFAULTS["search_rounds_max"],
        minimum=1,
        maximum=6,
    )
    if search_rounds_max is None:
        return None, err
    browse_candidates_per_search_max, err = _normalize_positive_int(
        raw.get("browse_candidates_per_search_max"),
        field="external_evidence_policy.browse_candidates_per_search_max",
        default=_EXTERNAL_EVIDENCE_DEFAULTS["browse_candidates_per_search_max"],
        minimum=1,
        maximum=10,
    )
    if browse_candidates_per_search_max is None:
        return None, err
    total_browse_steps_max, err = _normalize_positive_int(
        raw.get("total_browse_steps_max"),
        field="external_evidence_policy.total_browse_steps_max",
        default=_EXTERNAL_EVIDENCE_DEFAULTS["total_browse_steps_max"],
        minimum=1,
        maximum=12,
    )
    if total_browse_steps_max is None:
        return None, err
    return {
        "search_rounds_max": int(search_rounds_max),
        "browse_candidates_per_search_max": int(browse_candidates_per_search_max),
        "total_browse_steps_max": int(total_browse_steps_max),
    }, None


def validate_runtime_policy_bundle_v1(raw: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    bundle = dict(raw or {})
    if str(bundle.get("schema_version") or "").strip() != "1.0.0":
        return None, "schema_version must be 1.0.0"

    workspace_policy_id = str(bundle.get("workspace_policy_id") or "").strip()
    workspace_scope = str(bundle.get("workspace_scope") or "").strip()
    if not workspace_policy_id:
        return None, "workspace_policy_id is required"
    if not workspace_scope:
        return None, "workspace_scope is required"

    user_preference = bundle.get("user_preference_profile") or {}
    if not isinstance(user_preference, dict):
        return None, "user_preference_profile must be an object"
    communication_style = _normalize_text_list(user_preference.get("communication_style")) or [
        "clear",
        "honest",
        "concise",
    ]
    active_hours_local, err = _normalize_hour_list(user_preference.get("active_hours_local"), field="user_preference_profile.active_hours_local")
    if active_hours_local is None:
        return None, err
    risk_tolerance = str(user_preference.get("risk_tolerance") or "balanced").strip() or "balanced"
    if risk_tolerance not in _RISK_TOLERANCE:
        return None, "user_preference_profile.risk_tolerance must be low/balanced/high"

    execution_mode_policy = bundle.get("execution_mode_policy") or {}
    if not isinstance(execution_mode_policy, dict):
        return None, "execution_mode_policy must be an object"
    default_mode = str(execution_mode_policy.get("default_mode") or "balanced").strip() or "balanced"
    if default_mode not in _EXECUTION_MODES:
        return None, "execution_mode_policy.default_mode must be cost_saver/balanced/quality_first/chat_first"

    data_sensitivity_policy = bundle.get("data_sensitivity_policy") or {}
    if not isinstance(data_sensitivity_policy, dict):
        return None, "data_sensitivity_policy must be an object"
    default_level = str(data_sensitivity_policy.get("default_level") or "L1").strip() or "L1"
    if default_level not in _DATA_LEVELS:
        return None, "data_sensitivity_policy.default_level must be L0/L1/L2"
    storage_policy, err = _normalize_storage_policy(data_sensitivity_policy.get("storage_policy"))
    if storage_policy is None:
        return None, err

    proactivity_policy = bundle.get("proactivity_policy") or {}
    if not isinstance(proactivity_policy, dict):
        return None, "proactivity_policy must be an object"
    quiet_hours_local, err = _normalize_hour_list(proactivity_policy.get("quiet_hours_local"), field="proactivity_policy.quiet_hours_local")
    if quiet_hours_local is None:
        return None, err
    external_evidence_policy, err = _normalize_external_evidence_policy(bundle.get("external_evidence_policy"))
    if external_evidence_policy is None:
        return None, err

    normalized = {
        "schema_version": "1.0.0",
        "workspace_policy_id": workspace_policy_id,
        "workspace_scope": workspace_scope,
        "user_preference_profile": {
            "communication_style": communication_style,
            "response_language": (
                str(user_preference.get("response_language")).strip()
                if user_preference.get("response_language") is not None and str(user_preference.get("response_language")).strip()
                else None
            ),
            "active_hours_local": active_hours_local,
            "preferred_topics": _normalize_text_list(user_preference.get("preferred_topics")),
            "risk_tolerance": risk_tolerance,
        },
        "execution_mode_policy": {
            "default_mode": default_mode,
            "allow_user_override": bool(execution_mode_policy.get("allow_user_override", True)),
        },
        "data_sensitivity_policy": {
            "default_level": default_level,
            "storage_policy": storage_policy,
            "external_transfer_requires_confirmation": bool(
                data_sensitivity_policy.get("external_transfer_requires_confirmation", True)
            ),
        },
        "proactivity_policy": {
            "enabled": bool(proactivity_policy.get("enabled", False)),
            "quiet_hours_local": quiet_hours_local,
            "notify_on_mentions_only": bool(proactivity_policy.get("notify_on_mentions_only", True)),
            "max_pushes_per_day": max(0, int(proactivity_policy.get("max_pushes_per_day", 0) or 0)),
        },
        "external_evidence_policy": external_evidence_policy,
    }
    return normalized, None


def build_default_runtime_policy_bundle_v1(*, workspace_scope: str = "default") -> dict[str, Any]:
    normalized, _ = validate_runtime_policy_bundle_v1(
        {
            "schema_version": "1.0.0",
            "workspace_policy_id": "default",
            "workspace_scope": workspace_scope,
            "user_preference_profile": {
                "communication_style": ["clear", "honest", "concise"],
                "response_language": None,
                "active_hours_local": [],
                "preferred_topics": [],
                "risk_tolerance": "balanced",
            },
            "execution_mode_policy": {
                "default_mode": "balanced",
                "allow_user_override": True,
            },
            "data_sensitivity_policy": {
                "default_level": "L1",
                "storage_policy": {
                    "L0": "process_only",
                    "L1": "local_only",
                    "L2": "local_or_sync",
                },
                "external_transfer_requires_confirmation": True,
            },
            "proactivity_policy": {
                "enabled": False,
                "quiet_hours_local": [],
                "notify_on_mentions_only": True,
                "max_pushes_per_day": 0,
            },
            "external_evidence_policy": dict(_EXTERNAL_EVIDENCE_DEFAULTS),
        }
    )
    if normalized is None:
        raise ValueError("failed to build default runtime policy bundle")
    return normalized


class FileRuntimePolicyBundleStore:
    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        self._repo_root = Path(__file__).resolve().parents[3]
        self._config_root = self._repo_root / "configs" / "runtime_policy_bundles"
        self._override_root = Path(data_dir).resolve() / "runtime_policy_bundles"

    def _config_path(self, *, workspace_scope: str) -> Path:
        return self._config_root / f"{_safe_segment(workspace_scope, fallback='default')}.json"

    def _override_path(self, *, workspace_scope: str) -> Path:
        return self._override_root / f"{_safe_segment(workspace_scope, fallback='default')}.json"

    def _read(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        normalized, err = validate_runtime_policy_bundle_v1(obj if isinstance(obj, dict) else None)
        if err:
            return None
        return normalized

    def get(self, *, workspace_scope: str) -> dict[str, Any] | None:
        override = self._read(self._override_path(workspace_scope=workspace_scope))
        if override is not None:
            return override
        return self._read(self._config_path(workspace_scope=workspace_scope))

    def get_or_default(self, *, workspace_scope: str) -> dict[str, Any]:
        existing = self.get(workspace_scope=workspace_scope)
        if existing is not None:
            return existing
        fallback = self.get(workspace_scope="default")
        if fallback is not None:
            return fallback
        return build_default_runtime_policy_bundle_v1(workspace_scope=workspace_scope)

    def put(self, *, bundle: dict[str, Any]) -> None:
        normalized, err = validate_runtime_policy_bundle_v1(bundle)
        if normalized is None:
            raise ValueError(err or "invalid runtime policy bundle")
        path = self._override_path(workspace_scope=str(normalized["workspace_scope"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(normalized, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
