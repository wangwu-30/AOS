from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


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


def _normalize_style_packs(raw: Any, *, defaults: dict[str, Any]) -> dict[str, Any]:
    base = {
        "concise": {
            "tone": str(defaults.get("tone") or "direct").strip() or "direct",
            "verbosity": str(defaults.get("verbosity") or "concise").strip() or "concise",
            "traits": _normalize_text_list(defaults.get("style")) or ["clear", "honest", "concise"],
            "guidance": "prefer crisp, direct communication and avoid unnecessary flourish",
        },
        "formal": {
            "tone": "formal",
            "verbosity": "moderate",
            "traits": ["clear", "respectful", "structured"],
            "guidance": "use formal and respectful wording without changing the facts",
        },
        "witty": {
            "tone": "light",
            "verbosity": "concise",
            "traits": ["clear", "playful", "light_humor"],
            "guidance": "small amount of humor is allowed, but facts stay literal",
        },
        "dry_sarcastic": {
            "tone": "dry",
            "verbosity": "concise",
            "traits": ["clear", "dry", "restrained_sarcasm"],
            "guidance": "dry tone is allowed only when it does not create ambiguity or disrespect",
        },
    }
    if not isinstance(raw, dict):
        return base
    for pack_id, payload in raw.items():
        if not isinstance(payload, dict):
            continue
        base[str(pack_id)] = {
            "tone": str(payload.get("tone") or base.get(str(pack_id), {}).get("tone") or defaults.get("tone") or "direct").strip() or "direct",
            "verbosity": str(payload.get("verbosity") or base.get(str(pack_id), {}).get("verbosity") or defaults.get("verbosity") or "concise").strip() or "concise",
            "traits": _normalize_text_list(payload.get("traits")) or list(base.get(str(pack_id), {}).get("traits") or []),
            "guidance": str(payload.get("guidance") or base.get(str(pack_id), {}).get("guidance") or "").strip(),
        }
    return base


def _normalize_role_axioms(raw: Any) -> dict[str, Any]:
    base = {
        "task_processing_axioms": [
            "Task execution should follow evidence-backed hypothesis -> verify -> revise by default.",
            "When context is insufficient, request more context instead of hallucinating a missing fact.",
            "Act with independence, but remain inside legal, safety, platform, and runtime boundaries.",
        ],
        "communication_axioms": [
            "Communication style must not override truth, boundaries, or execution constraints.",
            "User-visible delivery should stay clear about certainty, blockers, and next steps.",
            "Respect the creator/user context without pretending to be the user's voice.",
        ],
        "planning_axioms": [
            "Select the domain and required context view before decomposing a task.",
            "Prefer minimal sufficient context over maximal context dumps.",
            "Choose quick lookup versus browser research doctrine explicitly before expanding a web task.",
        ],
        "verification_axioms": [
            "Do not mark a task done before evidence satisfies the delivery contract.",
            "Rejected paths require revised hypotheses or new evidence before retry.",
            "For adversarial reasoning, record the hypothesis, challenge, evidence, and revision path.",
        ],
    }
    if not isinstance(raw, dict):
        return base
    out: dict[str, Any] = {}
    for key, default_items in base.items():
        values = _normalize_text_list(raw.get(key))
        out[key] = values or list(default_items)
    return out


def _normalize_doctrine_packs(raw: Any) -> dict[str, Any]:
    base = {
        "scientific_hypothesis_mode": {
            "summary": "Use hypothesis -> verify -> revise/pass as the default task doctrine.",
            "steps": ["hypothesis", "verify", "revise_or_pass"],
            "verification_required": True,
        },
        "fast_path_mode": {
            "summary": "Low-risk tasks may use a shorter path, but still need explicit checks and evidence.",
            "steps": ["act", "quick_check", "deliver_or_escalate"],
            "verification_required": True,
        },
        "browser_research_mode": {
            "summary": "Use bounded search -> browse -> compare -> cite for research tasks that require external evidence.",
            "steps": ["search", "browse", "compare", "cite_or_block"],
            "verification_required": True,
        },
        "self_adversarial_mode": {
            "summary": "Use hypothesis -> challenge -> revision with audit evidence for complex or high-risk tasks.",
            "steps": ["hypothesis", "challenge", "revision", "verify_or_escalate"],
            "verification_required": True,
        },
    }
    if not isinstance(raw, dict):
        return base
    for pack_id, payload in raw.items():
        if not isinstance(payload, dict):
            continue
        base[str(pack_id)] = {
            "summary": str(payload.get("summary") or base.get(str(pack_id), {}).get("summary") or "").strip(),
            "steps": _normalize_text_list(payload.get("steps")) or list(base.get(str(pack_id), {}).get("steps") or []),
            "verification_required": bool(
                payload.get(
                    "verification_required",
                    base.get(str(pack_id), {}).get("verification_required", True),
                )
            ),
        }
    return base


def _convert_legacy_profile_v1(raw: dict[str, Any]) -> dict[str, Any]:
    defaults = dict(raw.get("communication_defaults") or {})
    style = _normalize_text_list(defaults.get("style")) or ["clear", "honest", "concise"]
    return {
        "schema_version": "2.0.0",
        "soul_profile_id": str(raw.get("soul_profile_id") or "").strip(),
        "name": str(raw.get("name") or "").strip(),
        "identity_summary": str(raw.get("identity_summary") or "").strip(),
        "principles": _normalize_text_list(raw.get("principles")),
        "boundary_rules": _normalize_text_list(raw.get("boundary_rules")),
        "communication_defaults": {
            "tone": str(defaults.get("tone") or "direct").strip() or "direct",
            "verbosity": str(defaults.get("verbosity") or "concise").strip() or "concise",
            "style": style,
            "external_action_policy": str(defaults.get("external_action_policy") or "ask_first").strip() or "ask_first",
        },
        "global_soul": {
            "identity_summary": str(raw.get("identity_summary") or "").strip(),
            "trust_principles": _normalize_text_list(raw.get("principles")),
            "boundary_rules": _normalize_text_list(raw.get("boundary_rules")),
            "external_action_policy": str(defaults.get("external_action_policy") or "ask_first").strip() or "ask_first",
        },
        "role_axioms": {},
        "style_packs": {},
        "doctrine_packs": {},
    }


def validate_soul_profile_v1(raw: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    profile = dict(raw or {})
    schema_version = str(profile.get("schema_version") or "1.0.0").strip() or "1.0.0"
    if schema_version == "1.0.0":
        profile = _convert_legacy_profile_v1(profile)
    elif schema_version != "2.0.0":
        return None, "schema_version must be 1.0.0 or 2.0.0"
    soul_profile_id = str(profile.get("soul_profile_id") or "").strip()
    name = str(profile.get("name") or "").strip()
    identity_summary = str(profile.get("identity_summary") or "").strip()
    if not soul_profile_id:
        return None, "soul_profile_id is required"
    if not name:
        return None, "name is required"
    if not identity_summary:
        return None, "identity_summary is required"
    principles = _normalize_text_list(profile.get("principles"))
    boundary_rules = _normalize_text_list(profile.get("boundary_rules"))
    defaults = profile.get("communication_defaults") or {}
    if not principles:
        return None, "principles must be a non-empty array"
    if not isinstance(defaults, dict):
        return None, "communication_defaults must be an object"
    style = _normalize_text_list(defaults.get("style"))
    if not style:
        style = ["clear", "honest", "concise"]
    external_action_policy = str(defaults.get("external_action_policy") or "ask_first").strip() or "ask_first"
    global_soul_raw = profile.get("global_soul") or {}
    if global_soul_raw is not None and not isinstance(global_soul_raw, dict):
        return None, "global_soul must be an object"
    role_axioms = _normalize_role_axioms(profile.get("role_axioms"))
    normalized = {
        "schema_version": "2.0.0",
        "soul_profile_id": soul_profile_id,
        "name": name,
        "identity_summary": identity_summary,
        "principles": principles,
        "communication_defaults": {
            "tone": str(defaults.get("tone") or "direct").strip() or "direct",
            "verbosity": str(defaults.get("verbosity") or "concise").strip() or "concise",
            "style": style,
            "external_action_policy": external_action_policy,
        },
        "boundary_rules": boundary_rules,
        "global_soul": {
            "identity_summary": (
                str(global_soul_raw.get("identity_summary") or "").strip()
                if isinstance(global_soul_raw, dict)
                else ""
            )
            or identity_summary,
            "trust_principles": _normalize_text_list(
                global_soul_raw.get("trust_principles") if isinstance(global_soul_raw, dict) else None
            )
            or principles,
            "boundary_rules": _normalize_text_list(
                global_soul_raw.get("boundary_rules") if isinstance(global_soul_raw, dict) else None
            )
            or boundary_rules,
            "external_action_policy": (
                str(global_soul_raw.get("external_action_policy") or "").strip()
                if isinstance(global_soul_raw, dict)
                else ""
            )
            or external_action_policy,
        },
        "role_axioms": role_axioms,
        "style_packs": _normalize_style_packs(profile.get("style_packs"), defaults=defaults),
        "doctrine_packs": _normalize_doctrine_packs(profile.get("doctrine_packs")),
    }
    return normalized, None


class FileSoulProfileStore:
    def __init__(self, data_dir: str | os.PathLike[str] = "data") -> None:
        self._repo_root = Path(__file__).resolve().parents[3]
        self._config_root = self._repo_root / "configs" / "soul_profiles"
        self._data_root = Path(data_dir).resolve() / "soul_profiles"

    def _config_path(self, *, soul_profile_id: str) -> Path:
        return self._config_root / f"{_safe_segment(soul_profile_id, fallback='soul')}.json"

    def _data_path(self, *, soul_profile_id: str) -> Path:
        return self._data_root / f"{_safe_segment(soul_profile_id, fallback='soul')}.json"

    def _read(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        normalized, err = validate_soul_profile_v1(obj if isinstance(obj, dict) else None)
        if err:
            return None
        return normalized

    def get(self, *, soul_profile_id: str) -> dict[str, Any] | None:
        override = self._read(self._data_path(soul_profile_id=soul_profile_id))
        if override is not None:
            return override
        return self._read(self._config_path(soul_profile_id=soul_profile_id))

    def put(self, *, profile: dict[str, Any]) -> None:
        normalized, err = validate_soul_profile_v1(profile)
        if normalized is None:
            raise ValueError(err or "invalid soul profile")
        path = self._data_path(soul_profile_id=str(normalized["soul_profile_id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(normalized, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
