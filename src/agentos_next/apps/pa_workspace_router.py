from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from agentos_next.apps.telegram_connector import MISSING_BUDGET
from agentos_next.apps.telegram_models import TelegramUpdate


class PAWorkspaceRouteUnmappedError(Exception):
    pass


@dataclass(frozen=True)
class PAWorkspaceRoute:
    workspace_id: str
    budget_slice_remote_llm_calls: Any = MISSING_BUDGET


class PAWorkspaceRouter:
    def __init__(self, routes_by_id: dict[str, PAWorkspaceRoute]) -> None:
        self._routes = dict(routes_by_id)

    @classmethod
    def from_json_file(cls, routing_file: str) -> "PAWorkspaceRouter":
        path = Path(routing_file)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("routing file must be a JSON object")

        route_obj = _extract_route_obj(payload)
        routes: dict[str, PAWorkspaceRoute] = {}
        for key, value in route_obj.items():
            route = _parse_route_value(key=str(key), value=value)
            routes[str(key)] = route
        if not routes:
            raise ValueError("routing file must include at least one route")
        return cls(routes)

    def route_for_payload(self, payload_str: str) -> Optional[PAWorkspaceRoute]:
        lookup_ids = _extract_lookup_ids(payload_str)
        if lookup_ids is None:
            return None
        for lookup_id in lookup_ids:
            route = self._routes.get(lookup_id)
            if route is not None:
                return route
        raise PAWorkspaceRouteUnmappedError()


def _extract_route_obj(payload: dict[str, Any]) -> dict[str, Any]:
    if "routes" in payload:
        route_obj = payload.get("routes")
        if not isinstance(route_obj, dict):
            raise ValueError("routes must be a JSON object")
        return route_obj

    if "conversation_id" in payload or "chat_id" in payload:
        merged: dict[str, Any] = {}
        for key in ("conversation_id", "chat_id"):
            group = payload.get(key)
            if group is None:
                continue
            if not isinstance(group, dict):
                raise ValueError(f"{key} must be a JSON object")
            for route_key, route_value in group.items():
                merged[str(route_key)] = route_value
        return merged

    return payload


def _parse_route_value(*, key: str, value: Any) -> PAWorkspaceRoute:
    if isinstance(value, str):
        workspace_id = value
        budget = MISSING_BUDGET
    elif isinstance(value, dict):
        workspace_id = str(value.get("workspace_id") or "").strip()
        if not workspace_id:
            raise ValueError(f"route '{key}' missing workspace_id")
        if "budget_slice_remote_llm_calls" in value:
            budget = value.get("budget_slice_remote_llm_calls")
        elif "budget" in value:
            budget = value.get("budget")
        else:
            budget = MISSING_BUDGET
    else:
        raise ValueError(f"route '{key}' must be string or object")

    if not workspace_id:
        raise ValueError(f"route '{key}' missing workspace_id")
    return PAWorkspaceRoute(workspace_id=workspace_id, budget_slice_remote_llm_calls=budget)


def _extract_lookup_ids(payload_str: str) -> Optional[list[str]]:
    try:
        payload = json.loads(payload_str)
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None

    try:
        update = TelegramUpdate.from_dict(payload)
    except Exception:
        return None

    out: list[str] = []

    def _append_if_present(value: Any) -> None:
        if value is None:
            return
        text = str(value).strip()
        if not text:
            return
        if text not in out:
            out.append(text)

    _append_if_present(payload.get("conversation_id"))
    _append_if_present(payload.get("chat_id"))

    message = payload.get("message")
    if isinstance(message, dict):
        _append_if_present(message.get("conversation_id"))
        _append_if_present(message.get("chat_id"))
        chat = message.get("chat")
        if isinstance(chat, dict):
            _append_if_present(chat.get("id"))

    if update.message is not None:
        _append_if_present(update.message.chat.id)

    return out
