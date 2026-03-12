from __future__ import annotations

from typing import Any, Iterable, Sequence

from agentos_next.kernel.capabilities import ALLOWED_CAPABILITY_NAMES, capability_items_for_policy_context


def _normalize_capability_names(raw: Iterable[str]) -> list[str]:
    names = [str(name).strip() for name in raw if str(name).strip()]
    names = list(dict.fromkeys(names))
    if "web_browse" in names and "web_search" not in names:
        names.append("web_search")
    return names


def _normalize_media_kinds(raw: Iterable[str]) -> list[str]:
    allowed = {"image", "document", "audio", "video"}
    out: list[str] = []
    for item in raw:
        value = str(item or "").strip().lower()
        if value and value in allowed and value not in out:
            out.append(value)
    return out


def _phase_backend_support(backend_name: str | None, model_id: str | None) -> dict[str, Any]:
    backend = str(backend_name or "local_mock").strip().lower()
    model = str(model_id or "").strip()
    support = {
        "backend": backend or "local_mock",
        "model": model or None,
        "supports_text": True,
        "supports_image": False,
        "supports_document": False,
        "supports_audio": False,
        "supports_video": False,
        "supports_file_reference": False,
    }
    if backend == "codex_oauth":
        support["supports_image"] = True
        support["supports_document"] = True
        support["supports_file_reference"] = True
    return support


def _build_multimodal_snapshot(
    *,
    submitter: str | None,
    bot_token: str,
    attachment_media_kinds: Sequence[str] | None,
    backend: str | None,
    model: str | None,
    planner_backend: str | None,
    planner_model: str | None,
    intent_backend: str | None,
    intent_model: str | None,
    communicator_backend: str | None,
    communicator_model: str | None,
) -> dict[str, Any]:
    submitter_name = str(submitter or "runtime.direct").strip().lower()
    ingress_media_kinds = _normalize_media_kinds(attachment_media_kinds or [])
    if submitter_name.startswith("telegram"):
        ingress_media_kinds = _normalize_media_kinds([*ingress_media_kinds, "image", "document", "audio", "video"])
    phase_backend_support = {
        "intent_router": _phase_backend_support(intent_backend or backend, intent_model or model),
        "planner": _phase_backend_support(planner_backend or backend, planner_model or model),
        "executor": _phase_backend_support(backend, model),
        "verifier_replanner": _phase_backend_support(backend, model),
        "communicator": _phase_backend_support(communicator_backend or backend, communicator_model or model),
    }
    download_supported_kinds = ingress_media_kinds if submitter_name.startswith("telegram") and str(bot_token or "").strip() else []
    artifact_pipeline = {
        "download_supported_kinds": list(download_supported_kinds),
        "evidence_supported_kinds": list(ingress_media_kinds),
        "artifact_supported_kinds": list(ingress_media_kinds),
    }
    return {
        "schema_version": "1.0.0",
        "type": "multimodal_runtime_capability_v1",
        "ingress_media_kinds": list(ingress_media_kinds),
        "artifact_pipeline": artifact_pipeline,
        "phase_backend_support": phase_backend_support,
    }


def build_effective_runtime_capabilities_v1(
    *,
    requested_capabilities: Sequence[str],
    allow_network_egress: bool,
    bot_token: str = "",
    submitter: str | None = None,
    attachment_media_kinds: Sequence[str] | None = None,
    backend: str | None = None,
    model: str | None = None,
    planner_backend: str | None = None,
    planner_model: str | None = None,
    intent_backend: str | None = None,
    intent_model: str | None = None,
    communicator_backend: str | None = None,
    communicator_model: str | None = None,
) -> dict[str, Any]:
    from agentos_next.runtime.builtin_web import probe_web_runtime_capability

    requested = _normalize_capability_names(requested_capabilities)
    web_probe = probe_web_runtime_capability(allow_network_egress=bool(allow_network_egress))
    multimodal = _build_multimodal_snapshot(
        submitter=submitter,
        bot_token=bot_token,
        attachment_media_kinds=attachment_media_kinds,
        backend=backend,
        model=model,
        planner_backend=planner_backend,
        planner_model=planner_model,
        intent_backend=intent_backend,
        intent_model=intent_model,
        communicator_backend=communicator_backend,
        communicator_model=communicator_model,
    )

    effective: list[str] = []
    disabled: list[dict[str, str]] = []

    def _disable(name: str, reason: str) -> None:
        disabled.append({"name": str(name).strip(), "reason": str(reason).strip()})

    for name in requested:
        if name == "telegram_send_document":
            _disable(name, "telegram primitives were removed after alignment cutover")
            continue
        if name not in ALLOWED_CAPABILITY_NAMES:
            _disable(name, "unknown capability")
            continue
        if name == "research_run":
            if not bool(web_probe.get("web_search_enabled")) or not bool(web_probe.get("web_browse_enabled")):
                _disable(name, "research_run requires both web_search and web_browse under current runtime gates")
                continue
            effective.append(name)
            continue
        if name == "web_search" and not bool(web_probe.get("web_search_enabled")):
            _disable(name, "no web search backend is available under current runtime gates")
            continue
        if name == "web_browse" and not bool(web_probe.get("web_browse_enabled")):
            _disable(
                name,
                str(web_probe.get("browse_unavailable_reason") or "no browse backend is available under current runtime gates"),
            )
            continue
        effective.append(name)

    if str(bot_token or "").strip():
        delivery_mode = "channel_adapter_available"
    else:
        delivery_mode = "channel_adapter_unconfigured"

    summary_lines: list[str] = []
    if "web_search" in effective:
        providers = [
            str(x).strip()
            for x in ((web_probe.get("backends") or {}).get("available") or [])
            if str(x).strip()
        ]
        if providers:
            summary_lines.append(f"web_search=available({','.join(providers)})")
    elif any(item.get("name") == "web_search" for item in disabled):
        summary_lines.append("web_search=disabled")
    if "web_browse" in effective:
        summary_lines.append("web_browse=available(playwright)")
    elif any(item.get("name") == "web_browse" for item in disabled):
        summary_lines.append("web_browse=disabled")
    if "research_run" in effective:
        summary_lines.append("research_run=available(search+browse)")
    elif any(item.get("name") == "research_run" for item in disabled):
        summary_lines.append("research_run=disabled")
    if "channel_send" in effective:
        summary_lines.append(f"channel_send=available({delivery_mode})")
    ingress_media = list(multimodal.get("ingress_media_kinds") or [])
    if ingress_media:
        summary_lines.append(f"multimodal_ingress=available({'|'.join(ingress_media)})")
    for item in disabled:
        summary_lines.append(f"{item['name']} pruned: {item['reason']}")

    return {
        "schema_version": "1.0.0",
        "type": "effective_runtime_capabilities_v1",
        "requested_capabilities": requested,
        "effective_capabilities": effective,
        "disabled_capabilities": disabled,
        "web": web_probe,
        "multimodal": multimodal,
        "delivery": {
            "channel_message_enabled": "channel_send" in effective,
            "adapter_mode": delivery_mode,
        },
        "summary_lines": summary_lines,
    }


def capability_names_from_effective_runtime_capabilities(snapshot: dict[str, Any] | None) -> list[str]:
    if not isinstance(snapshot, dict):
        return []
    return _normalize_capability_names(snapshot.get("effective_capabilities") or [])


def capability_items_from_effective_runtime_capabilities(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    return capability_items_for_policy_context(capability_names_from_effective_runtime_capabilities(snapshot))


def with_effective_runtime_capability_names(
    snapshot: dict[str, Any] | None,
    *,
    additional_names: Sequence[str],
) -> dict[str, Any]:
    base = dict(snapshot or {})
    effective = capability_names_from_effective_runtime_capabilities(base)
    merged = _normalize_capability_names([*effective, *additional_names])
    base["effective_capabilities"] = merged
    requested = _normalize_capability_names([*(base.get("requested_capabilities") or []), *additional_names])
    base["requested_capabilities"] = requested
    return base
