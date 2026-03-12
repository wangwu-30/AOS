from __future__ import annotations

import argparse
import difflib
import html
import json
import re
import sys
from http import HTTPStatus
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse


SCHEMA_VERSION = "1.0.0"


def _read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return _read_json_file(path)
    except Exception:
        return None


def _trace_path(data_dir: Path, trace_id: str) -> Path:
    return data_dir / "traces" / f"{trace_id}.jsonl"


def _event_path(data_dir: Path, workspace_id: str, event_id: str) -> Path:
    return data_dir / "pa" / "events" / workspace_id / f"{event_id}.json"


def _outbox_path(data_dir: Path, workspace_id: str, event_id: str) -> Path:
    return data_dir / "pa" / "outbox" / workspace_id / f"{event_id}.json"


def _task_graph_path(data_dir: Path, workspace_id: str, event_id: str) -> Path:
    return data_dir / "pa" / "task_graph" / workspace_id / f"{event_id}.json"


def _manifest_dir(data_dir: Path, trace_id: str) -> Path:
    return data_dir / "evidence" / "manifests" / trace_id


def _evidence_meta_path(data_dir: Path, ref: str) -> Path:
    return data_dir / "evidence" / "meta" / f"{ref}.json"


def _evidence_blob_path(data_dir: Path, ref: str) -> Path:
    return data_dir / "evidence" / "blobs" / ref


def _idempotency_path(data_dir: Path, workspace_id: str, idempotency_key: str) -> Path:
    return data_dir / "idempotency" / workspace_id / f"{idempotency_key}.json"


def _load_trace_events(*, data_dir: Path, trace_id: str, turn_id: Optional[str]) -> tuple[list[dict[str, Any]], Path]:
    path = _trace_path(data_dir, trace_id)
    if not path.exists():
        return [], path
    events: list[dict[str, Any]] = []
    for idx, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        ctx = obj.get("ctx")
        if turn_id and isinstance(ctx, dict) and str(ctx.get("turn_id") or "") != turn_id:
            continue
        obj = dict(obj)
        obj["line_no"] = idx
        events.append(obj)
    return events, path


def _normalize_ref(ref: Any) -> str:
    value = str(ref or "").strip()
    return value


def _ref_from_obj(obj: Any) -> str:
    if isinstance(obj, dict):
        return _normalize_ref(obj.get("ref"))
    return _normalize_ref(obj)


def _append_ref_source(ref_sources: dict[str, set[str]], ref: str, source: str) -> None:
    if not ref:
        return
    ref_sources.setdefault(ref, set()).add(source)


def _collect_refs_from_trace(events: list[dict[str, Any]], ref_sources: dict[str, set[str]]) -> None:
    for event in events:
        event_type = str(event.get("event_type") or "UNKNOWN")
        line_no = int(event.get("line_no") or 0)
        for er in event.get("evidence_refs") or []:
            ref = _ref_from_obj(er)
            _append_ref_source(ref_sources, ref, f"trace:{event_type}:line_{line_no}")


def _collect_refs_from_manifest(manifests: list[dict[str, Any]], ref_sources: dict[str, set[str]]) -> None:
    for item in manifests:
        turn_id = str(item.get("turn_id") or "")
        manifest = item.get("manifest")
        if not isinstance(manifest, dict):
            continue
        for er in manifest.get("evidence_refs") or []:
            ref = _ref_from_obj(er)
            _append_ref_source(ref_sources, ref, f"manifest:{turn_id or 'unknown_turn'}")


def _collect_refs_from_outbox(outbox_obj: Any, ref_sources: dict[str, set[str]]) -> None:
    if not isinstance(outbox_obj, dict):
        return
    execute = outbox_obj.get("execute")
    if isinstance(execute, dict):
        for ref in execute.get("evidence_refs") or []:
            _append_ref_source(ref_sources, _ref_from_obj(ref), "pa_outbox:execute")
    for ref in outbox_obj.get("metering_evidence_refs") or []:
        _append_ref_source(ref_sources, _ref_from_obj(ref), "pa_outbox:metering")


def _load_turn_manifests(*, data_dir: Path, trace_id: str, turn_id: Optional[str]) -> list[dict[str, Any]]:
    root = _manifest_dir(data_dir, trace_id)
    if not root.exists():
        return []
    manifests: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        if turn_id and path.stem != turn_id:
            continue
        obj = _safe_read_json(path)
        manifests.append(
            {
                "turn_id": path.stem,
                "path": str(path),
                "signature_path": str(path.with_suffix(path.suffix + ".sig")),
                "manifest": obj,
            }
        )
    return manifests


def _decode_blob(content_type: str, content: bytes) -> tuple[str, Any]:
    if content_type == "application/json":
        try:
            return "json", json.loads(content.decode("utf-8"))
        except Exception:
            return "text", content.decode("utf-8", errors="replace")
    if content_type.startswith("text/"):
        return "text", content.decode("utf-8", errors="replace")
    return "bytes_hex", content.hex()


def _looks_like_context_snapshot(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if "selection_trace" in value:
        return True
    context_plane_keys = {"execution_plane", "communication_plane", "retrospective_plane", "constraint_plane"}
    if context_plane_keys.intersection(value.keys()):
        return True
    if "selected_refs" in value or "decision_log" in value:
        return True
    return False


def _classify_evidence_item(item: dict[str, Any]) -> str:
    kind = str(item.get("kind") or "")
    if kind == "llm_io":
        if "text" in item:
            return "prompts"
        return "llm_outputs"
    if kind == "tool_io":
        return "tool_io"
    if kind == "policy":
        return "policies"
    if kind == "context_routing":
        return "context"
    if kind == "routing":
        return "context"
    if kind == "snapshot":
        if _looks_like_context_snapshot(item.get("json")):
            return "context"
        return "snapshots"
    if kind == "error":
        return "errors"
    return "other"


def _load_evidence_items(*, data_dir: Path, ref_sources: dict[str, set[str]]) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    grouped: dict[str, list[dict[str, Any]]] = {
        "prompts": [],
        "llm_outputs": [],
        "tool_io": [],
        "policies": [],
        "context": [],
        "snapshots": [],
        "errors": [],
        "other": [],
    }
    missing_refs: list[str] = []
    for ref in sorted(ref_sources.keys()):
        meta_path = _evidence_meta_path(data_dir, ref)
        blob_path = _evidence_blob_path(data_dir, ref)
        if not meta_path.exists() or not blob_path.exists():
            missing_refs.append(ref)
            continue
        meta = _safe_read_json(meta_path)
        if not isinstance(meta, dict):
            missing_refs.append(ref)
            continue
        try:
            content = blob_path.read_bytes()
        except Exception:
            missing_refs.append(ref)
            continue
        content_type = str(meta.get("content_type") or "application/octet-stream")
        body_kind, body_value = _decode_blob(content_type, content)
        item: dict[str, Any] = {
            "ref": ref,
            "kind": str(meta.get("kind") or ""),
            "ts": str(meta.get("ts") or ""),
            "size_bytes": int(meta.get("size_bytes") or 0),
            "content_type": content_type,
            "sha256": str(meta.get("sha256") or ""),
            "sources": sorted(ref_sources.get(ref) or []),
        }
        if body_kind == "json":
            item["json"] = body_value
        elif body_kind == "text":
            item["text"] = body_value
        else:
            item["bytes_hex"] = body_value
        grouped[_classify_evidence_item(item)].append(item)
    return grouped, missing_refs


def _resolve_trace_id(*, event_id: Optional[str], trace_id: Optional[str], outbox_obj: Any, data_dir: Path) -> str:
    if trace_id:
        return trace_id
    if isinstance(outbox_obj, dict):
        trace = outbox_obj.get("trace")
        if isinstance(trace, dict):
            resolved = str(trace.get("trace_id") or "").strip()
            if resolved:
                return resolved
    if event_id:
        guessed = f"tr_pa_{event_id}"
        if _trace_path(data_dir, guessed).exists():
            return guessed
    return ""


def _resolve_turn_id(*, turn_id: Optional[str], outbox_obj: Any) -> str:
    if turn_id:
        return turn_id
    if isinstance(outbox_obj, dict):
        trace = outbox_obj.get("trace")
        if isinstance(trace, dict):
            resolved = str(trace.get("turn_id") or "").strip()
            if resolved:
                return resolved
    return ""


def _load_pa_task_executions(
    *,
    data_dir: Path,
    workspace_id: str,
    event_id: Optional[str],
    task_graph_obj: Any,
    ref_sources: dict[str, set[str]],
) -> list[dict[str, Any]]:
    if not event_id or not isinstance(task_graph_obj, dict):
        return []
    tasks = task_graph_obj.get("tasks")
    if not isinstance(tasks, list):
        return []
    out: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("task_id") or "").strip()
        if not task_id:
            continue
        idem_key = f"tg_{event_id}_{task_id}"
        path = _idempotency_path(data_dir, workspace_id, idem_key)
        obj = _safe_read_json(path)
        if not isinstance(obj, dict):
            continue
        result = obj.get("result")
        if isinstance(result, dict):
            for er in result.get("evidence_refs") or []:
                _append_ref_source(ref_sources, _ref_from_obj(er), f"idempotency:{task_id}")
        out.append(
            {
                "task_id": task_id,
                "task_type": (task.get("payload") or {}).get("type") if isinstance(task.get("payload"), dict) else None,
                "idempotency_key": idem_key,
                "path": str(path),
                "record": obj,
            }
        )
    out.sort(key=lambda item: str(item.get("task_id") or ""))
    return out


def _build_prompt_assembly(evidence: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    context_refs = [str(item.get("ref")) for item in evidence.get("context", [])]
    tool_refs = [str(item.get("ref")) for item in evidence.get("tool_io", [])]
    policy_refs = [str(item.get("ref")) for item in evidence.get("policies", [])]
    prompt_refs = [str(item.get("ref")) for item in evidence.get("prompts", [])]
    output_refs = [str(item.get("ref")) for item in evidence.get("llm_outputs", [])]
    notes = [
        "prompts 为实际发送给模型的文本 evidence。",
        "context/tool/policy 分组展示了 prompt 可能依赖的上下文装配、输入与约束证据。",
    ]
    return {
        "prompt_refs": prompt_refs,
        "tool_io_refs": tool_refs,
        "context_refs": context_refs,
        "policy_refs": policy_refs,
        "llm_output_refs": output_refs,
        "notes": notes,
    }


def _dom_id(prefix: str, value: Any) -> str:
    token = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip()).strip("-").lower()
    return f"{prefix}-{token or 'item'}"


def _task_ids_from_sources(sources: Any) -> list[str]:
    out: list[str] = []
    if isinstance(sources, list):
        for raw in sources:
            text = str(raw or "").strip()
            if text.startswith("idempotency:"):
                task_id = text.split(":", 1)[1].strip()
                if task_id and task_id not in out:
                    out.append(task_id)
    return out or ["root"]


def _task_ids_from_trace_event(event: dict[str, Any]) -> list[str]:
    if not isinstance(event, dict):
        return ["root"]
    ctx = event.get("ctx")
    span_id = str((ctx or {}).get("span_id") or "").strip() if isinstance(ctx, dict) else ""
    match = re.search(r"(task_[A-Za-z0-9_-]+)$", span_id)
    if match:
        return [match.group(1)]
    parent_span_id = str((ctx or {}).get("parent_span_id") or "").strip() if isinstance(ctx, dict) else ""
    match = re.search(r"(task_[A-Za-z0-9_-]+)$", parent_span_id)
    if match:
        return [match.group(1)]
    data = event.get("data")
    direct_task_id = str((data or {}).get("task_id") or "").strip() if isinstance(data, dict) else ""
    if direct_task_id:
        return [direct_task_id]
    return ["root"]


def _script_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _collect_task_focus_items(
    *,
    task_graph: Any,
    task_executions: list[dict[str, Any]],
    evidence: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}

    def _ensure(task_id: str) -> dict[str, Any]:
        if task_id not in items:
            items[task_id] = {
                "task_id": task_id,
                "label": task_id,
                "task_type": "root" if task_id == "root" else "",
                "state": "",
                "error_code": "",
                "refs": [],
                "execution_anchor": "",
                "task_bundle": {},
                "file_refs": [],
                "task_execution_policy": {},
                "context_snapshot_ref": "",
                "read_only_ancestor_context_refs": [],
                "bundle_sufficient_for_execution": None,
                "result_capsule_ids": [],
            }
        return items[task_id]

    if isinstance(task_graph, dict):
        for task in task_graph.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("task_id") or "").strip()
            if not task_id:
                continue
            entry = _ensure(task_id)
            payload = task.get("payload") or {}
            if isinstance(payload, dict):
                entry["task_type"] = str(payload.get("type") or entry.get("task_type") or "")
            entry["state"] = str(task.get("state") or entry.get("state") or "")
            entry["error_code"] = str(task.get("error_code") or entry.get("error_code") or "")
            if isinstance(task.get("task_bundle"), dict):
                entry["task_bundle"] = dict(task.get("task_bundle") or {})
            if isinstance(task.get("task_execution_policy"), dict):
                entry["task_execution_policy"] = dict(task.get("task_execution_policy") or {})
            if isinstance(task.get("file_refs"), list):
                entry["file_refs"] = [dict(item) for item in (task.get("file_refs") or []) if isinstance(item, dict)]
            entry["context_snapshot_ref"] = str(task.get("context_snapshot_ref") or entry.get("context_snapshot_ref") or "")
            entry["read_only_ancestor_context_refs"] = [
                str(item).strip()
                for item in (task.get("read_only_ancestor_context_refs") or [])
                if str(item).strip()
            ]
            if task.get("sufficient_for_execution") is not None:
                entry["bundle_sufficient_for_execution"] = bool(task.get("sufficient_for_execution"))
        for capsule in task_graph.get("result_capsules") or []:
            if not isinstance(capsule, dict):
                continue
            task_id = str(capsule.get("task_id") or "").strip()
            if not task_id:
                continue
            entry = _ensure(task_id)
            capsule_id = str(capsule.get("id") or "").strip()
            if capsule_id and capsule_id not in entry["result_capsule_ids"]:
                entry["result_capsule_ids"].append(capsule_id)
            for ref in capsule.get("evidence_refs") or []:
                ref_value = str(ref or "").strip()
                if ref_value and ref_value not in entry["refs"]:
                    entry["refs"].append(ref_value)

    for task_exec in task_executions if isinstance(task_executions, list) else []:
        if not isinstance(task_exec, dict):
            continue
        task_id = str(task_exec.get("task_id") or "").strip()
        if not task_id:
            continue
        entry = _ensure(task_id)
        entry["execution_anchor"] = _dom_id("task-exec", task_id)
        record = task_exec.get("record") or {}
        result = record.get("result") if isinstance(record, dict) else {}
        if isinstance(result, dict):
            for ref in result.get("evidence_refs") or []:
                ref_value = _ref_from_obj(ref)
                if ref_value and ref_value not in entry["refs"]:
                    entry["refs"].append(ref_value)

    for group_items in evidence.values():
        if not isinstance(group_items, list):
            continue
        for item in group_items:
            if not isinstance(item, dict):
                continue
            task_ids = _task_ids_from_sources(item.get("sources"))
            ref = str(item.get("ref") or "").strip()
            for task_id in task_ids:
                entry = _ensure(task_id)
                if ref and ref not in entry["refs"]:
                    entry["refs"].append(ref)

    ordered = sorted(
        items.values(),
        key=lambda item: (
            0 if str(item.get("task_id") or "") == "root" else 1,
            str(item.get("task_id") or ""),
        ),
    )
    return ordered


def _iter_evidence_json(evidence: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for group_items in evidence.values():
        if not isinstance(group_items, list):
            continue
        for item in group_items:
            if isinstance(item, dict) and isinstance(item.get("json"), dict):
                out.append(item)
    return out


def _find_latest_evidence_json_by_type(evidence: dict[str, list[dict[str, Any]]], type_name: str) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for item in _iter_evidence_json(evidence):
        obj = item.get("json") or {}
        if str(obj.get("type") or "").strip() != type_name:
            continue
        latest = dict(obj)
    return latest


def _build_runtime_debug_payload(
    evidence: dict[str, list[dict[str, Any]]],
    task_focus_items: list[dict[str, Any]],
    task_graph: Any,
) -> dict[str, Any]:
    query_obj = _find_latest_evidence_json_by_type(evidence, "query_gated_query_v1")
    assistant_result = _find_latest_evidence_json_by_type(evidence, "assistant_loop_result")
    graph_obj = dict(task_graph or {}) if isinstance(task_graph, dict) else {}
    graph_tasks = [dict(item) for item in (graph_obj.get("tasks") or []) if isinstance(item, dict)]
    root_task = graph_tasks[0] if graph_tasks else {}
    task_bundle = (
        dict(root_task.get("task_bundle") or {})
        if isinstance(root_task.get("task_bundle"), dict)
        else dict(query_obj.get("task_bundle") or {})
        if isinstance(query_obj.get("task_bundle"), dict)
        else {}
    )
    execution_policy = (
        dict(root_task.get("task_execution_policy") or {})
        if isinstance(root_task.get("task_execution_policy"), dict)
        else dict(query_obj.get("task_execution_policy") or {})
        if isinstance(query_obj.get("task_execution_policy"), dict)
        else dict(task_bundle.get("task_execution_policy") or {})
        if isinstance(task_bundle.get("task_execution_policy"), dict)
        else {}
    )
    file_refs = [
        dict(item)
        for item in (
            root_task.get("file_refs")
            or query_obj.get("file_refs")
            or task_bundle.get("file_refs")
            or []
        )
        if isinstance(item, dict)
    ]
    leader_rail: list[dict[str, Any]] = []
    steps = list(assistant_result.get("steps") or []) if isinstance(assistant_result.get("steps"), list) else []
    graph_leader_decisions = [dict(item) for item in (graph_obj.get("leader_decisions") or []) if isinstance(item, dict)]
    if graph_leader_decisions:
        leader_rail = sorted(
            graph_leader_decisions,
            key=lambda item: int(item.get("step_index") or 0),
        )
    else:
        leader_phases = ["intent_router", "planner", "verifier_replanner", "communicator"]
        for phase in leader_phases:
            matched = None
            for item in reversed(steps):
                if not isinstance(item, dict):
                    continue
                if str(item.get("internal_role_phase") or "").strip() == phase:
                    matched = item
                    break
            leader_rail.append(
                {
                    "phase": phase,
                    "status": str((matched or {}).get("status") or "missing"),
                    "error_code": str((matched or {}).get("error_code") or ""),
                    "deadline_ms": int((matched or {}).get("deadline_ms") or 0),
                }
            )
    context_chain = {
        "context_snapshot_ref": str(root_task.get("context_snapshot_ref") or task_bundle.get("context_snapshot_ref") or ""),
        "read_only_ancestor_context_refs": [
            str(item).strip()
            for item in (
                root_task.get("read_only_ancestor_context_refs")
                or task_bundle.get("read_only_ancestor_context_refs")
                or []
            )
            if str(item).strip()
        ],
        "bundle_sufficient_for_execution": bool(
            root_task.get("sufficient_for_execution")
            if root_task.get("sufficient_for_execution") is not None
            else task_bundle.get("sufficient_for_execution")
        ),
        "worker_task_admission_mode": str(root_task.get("worker_task_admission_mode") or task_bundle.get("worker_task_admission_mode") or ""),
        "context_escalation_mode": str(root_task.get("context_escalation_mode") or task_bundle.get("context_escalation_mode") or ""),
    }
    plan_revisions = [dict(item) for item in (graph_obj.get("plan_revisions") or []) if isinstance(item, dict)]
    result_capsules = [dict(item) for item in (graph_obj.get("result_capsules") or []) if isinstance(item, dict)]
    message_turns = [dict(item) for item in (graph_obj.get("message_turns") or []) if isinstance(item, dict)]
    retry_timeout_events = [
        {
            "phase": str(item.get("internal_role_phase") or item.get("source_phase") or item.get("operator_ref") or ""),
            "status": str(item.get("status") or ""),
            "deadline_ms": int(item.get("deadline_ms") or 0),
            "attempts": int(((item.get("task_bundle") or {}).get("attempts")) or item.get("attempts") or 0),
        }
        for item in steps
        if isinstance(item, dict) and (str(item.get("status") or "") == "timeout" or int(item.get("deadline_ms") or 0) > 0)
    ]
    return {
        "task_bundle": task_bundle,
        "task_execution_policy": execution_policy,
        "file_refs": file_refs,
        "leader_rail": leader_rail,
        "context_chain": context_chain,
        "plan_revisions": plan_revisions,
        "result_capsules": result_capsules,
        "message_turns": message_turns,
        "retry_timeout_events": retry_timeout_events,
        "assistant_result": assistant_result,
        "query": query_obj,
        "task_focus_items": task_focus_items,
    }


def build_trace_view(
    *,
    data_dir: str | Path = "data",
    trace_id: Optional[str] = None,
    event_id: Optional[str] = None,
    workspace_id: str = "local",
    turn_id: Optional[str] = None,
) -> dict[str, Any]:
    base = Path(data_dir)
    event_value = str(event_id or "").strip() or None
    workspace_value = str(workspace_id or "local").strip() or "local"

    pa_event = _safe_read_json(_event_path(base, workspace_value, event_value)) if event_value else None
    pa_outbox = _safe_read_json(_outbox_path(base, workspace_value, event_value)) if event_value else None
    task_graph = _safe_read_json(_task_graph_path(base, workspace_value, event_value)) if event_value else None

    resolved_trace_id = _resolve_trace_id(event_id=event_value, trace_id=str(trace_id or "").strip() or None, outbox_obj=pa_outbox, data_dir=base)
    resolved_turn_id = _resolve_turn_id(turn_id=str(turn_id or "").strip() or None, outbox_obj=pa_outbox) or None

    ref_sources: dict[str, set[str]] = {}
    trace_events: list[dict[str, Any]] = []
    trace_file = _trace_path(base, resolved_trace_id) if resolved_trace_id else None
    manifests: list[dict[str, Any]] = []

    if resolved_trace_id:
        trace_events, trace_file = _load_trace_events(data_dir=base, trace_id=resolved_trace_id, turn_id=resolved_turn_id)
        manifests = _load_turn_manifests(data_dir=base, trace_id=resolved_trace_id, turn_id=resolved_turn_id)
        _collect_refs_from_trace(trace_events, ref_sources)
        _collect_refs_from_manifest(manifests, ref_sources)

    _collect_refs_from_outbox(pa_outbox, ref_sources)
    task_executions = _load_pa_task_executions(
        data_dir=base,
        workspace_id=workspace_value,
        event_id=event_value,
        task_graph_obj=task_graph,
        ref_sources=ref_sources,
    )

    evidence, missing_refs = _load_evidence_items(data_dir=base, ref_sources=ref_sources)
    prompt_assembly = _build_prompt_assembly(evidence)
    runtime_debug = _build_runtime_debug_payload(
        evidence=evidence,
        task_focus_items=_collect_task_focus_items(
            task_graph=task_graph,
            task_executions=task_executions,
            evidence=evidence,
        ),
        task_graph=task_graph,
    )

    has_partial = any(
        value is not None and value != []
        for value in (pa_event, pa_outbox, task_graph, task_executions, evidence.get("prompts"), evidence.get("llm_outputs"))
    )
    trace_exists = bool(trace_file and trace_file.exists())

    error_code: Optional[str] = None
    ok = trace_exists
    if not resolved_trace_id and not event_value:
        error_code = "E_INPUT_SCHEMA"
    elif resolved_trace_id and not trace_exists:
        error_code = "E_TRACE_NOT_FOUND"
    elif event_value and not has_partial and not trace_exists:
        error_code = "E_EVENT_NOT_FOUND"

    summary = {
        "trace_event_count": len(trace_events),
        "manifest_count": len(manifests),
        "task_execution_count": len(task_executions),
        "prompt_count": len(evidence.get("prompts") or []),
        "llm_output_count": len(evidence.get("llm_outputs") or []),
        "error_count": len(evidence.get("errors") or []),
        "evidence_ref_count": len(ref_sources),
        "missing_ref_count": len(missing_refs),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "error_code": error_code,
        "requested": {
            "data_dir": str(base),
            "trace_id": str(trace_id or ""),
            "turn_id": str(turn_id or ""),
            "event_id": str(event_value or ""),
            "workspace_id": workspace_value,
        },
        "resolved": {
            "trace_id": str(resolved_trace_id or ""),
            "turn_id": str(resolved_turn_id or ""),
            "trace_path": str(trace_file) if trace_file is not None else "",
        },
        "summary": summary,
        "prompt_assembly": prompt_assembly,
        "runtime_debug": runtime_debug,
        "trace": {
            "events": trace_events,
            "manifests": manifests,
        },
        "evidence": evidence,
        "missing_refs": missing_refs,
        "pa": {
            "event": pa_event,
            "outbox": pa_outbox,
            "task_graph": task_graph,
            "task_executions": task_executions,
        },
    }


def render_trace_view_html(view: dict[str, Any]) -> str:
    summary = view.get("summary") or {}
    evidence = view.get("evidence") or {}
    prompt_assembly = view.get("prompt_assembly") or {}
    resolved = view.get("resolved") or {}
    requested = view.get("requested") or {}
    pa = view.get("pa") or {}
    trace = view.get("trace") or {}
    session = view.get("session") or {}
    runtime_debug = view.get("runtime_debug") or {}
    task_focus_items = _collect_task_focus_items(
        task_graph=pa.get("task_graph"),
        task_executions=list(pa.get("task_executions") or []),
        evidence=evidence if isinstance(evidence, dict) else {},
    )

    title = str((resolved.get("trace_id") or requested.get("event_id") or "trace_view")).strip() or "trace_view"
    ok = bool(view.get("ok"))
    status_text = "TRACE READY" if ok else f"TRACE INCOMPLETE · {str(view.get('error_code') or 'unknown')}"

    def _pretty(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        except Exception:
            return str(value)

    def _render_meta_line(item: dict[str, Any]) -> str:
        parts = [
            f"<span class='chip'>{html.escape(str(item.get('kind') or ''))}</span>",
            f"<span class='chip'>{html.escape(str(item.get('ref') or ''))}</span>",
        ]
        if item.get("size_bytes") is not None:
            parts.append(f"<span class='chip'>{int(item.get('size_bytes') or 0)} bytes</span>")
        return "".join(parts)

    def _render_sources(item: dict[str, Any]) -> str:
        sources = item.get("sources") or []
        if not isinstance(sources, list) or not sources:
            return ""
        chips = "".join(f"<span class='chip muted'>{html.escape(str(src))}</span>" for src in sources)
        return f"<div class='sources'>{chips}</div>"

    def _render_payload(item: dict[str, Any]) -> str:
        if "text" in item:
            payload = str(item.get("text") or "")
        elif "json" in item:
            payload = _pretty(item.get("json"))
        else:
            payload = _pretty(item)
        return f"<pre>{html.escape(payload)}</pre>"

    def _task_ids_attr(task_ids: list[str]) -> str:
        return html.escape(" ".join(task_ids))

    def _render_task_chips(task_ids: list[str]) -> str:
        if not task_ids:
            return ""
        return "".join(f"<span class='chip task-chip'>{html.escape(task_id)}</span>" for task_id in task_ids)

    def _render_evidence_group(label: str, items: list[dict[str, Any]], tone: str) -> str:
        if not items:
            return (
                f"<section class='panel {tone}'>"
                f"<h2>{html.escape(label)}</h2>"
                "<p class='empty'>Empty</p>"
                "</section>"
            )
        cards = []
        for item in items:
            task_ids = _task_ids_from_sources(item.get("sources"))
            ref = str(item.get("ref") or "").strip()
            card_id = _dom_id("evidence", ref or label)
            cards.append(
                f"<details class='item-card filterable trace-record evidence-record' id='{html.escape(card_id)}' data-task-ids='{_task_ids_attr(task_ids)}' open>"
                f"<summary><div class='summary-head'>{_render_meta_line(item)}{_render_task_chips(task_ids)}</div></summary>"
                f"{_render_sources(item)}"
                f"{_render_payload(item)}"
                "</details>"
            )
        return f"<section class='panel {tone}'><h2>{html.escape(label)}</h2>{''.join(cards)}</section>"

    def _render_diff_group(label: str, items: list[dict[str, Any]]) -> str:
        if len(items) < 2:
            return f"<section class='panel slate'><h2>{html.escape(label)}</h2><p class='empty'>Need at least two items to diff.</p></section>"
        cards = []
        for idx in range(1, len(items)):
            before = items[idx - 1]
            after = items[idx]
            before_text = str(before.get("text") if "text" in before else _pretty(before.get("json") or before))
            after_text = str(after.get("text") if "text" in after else _pretty(after.get("json") or after))
            task_ids = sorted(set(_task_ids_from_sources(before.get("sources")) + _task_ids_from_sources(after.get("sources"))))
            diff_lines = list(
                difflib.unified_diff(
                    before_text.splitlines(),
                    after_text.splitlines(),
                    fromfile=str(before.get("ref") or f"{label.lower()}_{idx}"),
                    tofile=str(after.get("ref") or f"{label.lower()}_{idx+1}"),
                    lineterm="",
                )
            )
            rendered = []
            for line in diff_lines or ["(no textual diff)"]:
                cls = "diff-ctx"
                if line.startswith("+++ ") or line.startswith("--- ") or line.startswith("@@"):
                    cls = "diff-hdr"
                elif line.startswith("+") and not line.startswith("+++"):
                    cls = "diff-add"
                elif line.startswith("-") and not line.startswith("---"):
                    cls = "diff-del"
                rendered.append(f"<span class='{cls}'>{html.escape(line)}</span>")
            cards.append(
                f"<details class='item-card filterable trace-record diff-record' data-task-ids='{_task_ids_attr(task_ids)}'>"
                "<summary>"
                f"<div class='summary-head'><span class='chip'>{html.escape(str(before.get('ref') or ''))}</span>"
                f"<span class='chip muted'>→</span><span class='chip'>{html.escape(str(after.get('ref') or ''))}</span>{_render_task_chips(task_ids)}</div>"
                "</summary>"
                f"<pre class='diff'>{''.join(rendered)}</pre>"
                "</details>"
            )
        return f"<section class='panel slate'><h2>{html.escape(label)}</h2>{''.join(cards)}</section>"

    def _render_runtime_pairs(pairs: list[tuple[str, Any]]) -> str:
        rows = []
        for label, value in pairs:
            rendered = html.escape(_pretty(value) if isinstance(value, (dict, list)) else str(value))
            rows.append(f"<div class='kv-row'><span class='kv-label'>{html.escape(label)}</span><span class='kv-value'>{rendered}</span></div>")
        return "".join(rows)

    def _render_file_refs(items: list[dict[str, Any]]) -> str:
        if not items:
            return "<p class='empty'>No file refs</p>"
        cards = []
        for item in items:
            cards.append(
                "<details class='item-card' open>"
                f"<summary><div class='summary-head'><span class='chip'>{html.escape(str(item.get('ref_type') or ''))}</span>"
                f"<span class='chip muted'>{html.escape(str(item.get('usage') or ''))}</span>"
                f"<span class='chip'>{html.escape(str(item.get('resolver') or ''))}</span></div></summary>"
                f"<pre>{html.escape(_pretty(item))}</pre>"
                "</details>"
            )
        return "".join(cards)

    events = trace.get("events") or []
    event_rows = []
    for event in events if isinstance(events, list) else []:
        ctx = event.get("ctx") or {}
        data = event.get("data") or {}
        task_ids = _task_ids_from_trace_event(event if isinstance(event, dict) else {})
        line_no = int(event.get("line_no") or 0)
        event_rows.append(
            f"<tr class='filterable trace-record timeline-row' id='{html.escape(_dom_id('trace-line', line_no))}' data-task-ids='{_task_ids_attr(task_ids)}'>"
            f"<td><div class='task-cell'><button class='mini-button timeline-focus' type='button' data-task-focus='{html.escape(task_ids[0])}'>Focus</button><span>{line_no}</span></div></td>"
            f"<td>{html.escape(str(event.get('ts') or ''))}</td>"
            f"<td><span class='event'>{html.escape(str(event.get('event_type') or ''))}</span>{_render_task_chips(task_ids)}</td>"
            f"<td>{html.escape(str(ctx.get('span_id') or ''))}</td>"
            f"<td><pre>{html.escape(_pretty(data))}</pre></td>"
            "</tr>"
        )
    timeline_html = (
        "<section class='panel slate'>"
        "<h2>Trace Timeline</h2>"
        "<div class='table-wrap'><table><thead><tr><th>Line</th><th>Time</th><th>Event</th><th>Span</th><th>Data</th></tr></thead>"
        f"<tbody>{''.join(event_rows) if event_rows else '<tr><td colspan=\"5\" class=\"empty-cell\">No trace events</td></tr>'}</tbody>"
        "</table></div></section>"
    )

    task_graph = pa.get("task_graph")
    task_rows = []
    if isinstance(task_graph, dict):
        for task in task_graph.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("task_id") or "").strip()
            task_rows.append(
                f"<tr class='filterable task-row' data-task-ids='{html.escape(task_id)}'>"
                f"<td><div class='task-cell'><button class='mini-button' type='button' data-task-focus='{html.escape(task_id)}'>Focus</button><span>{html.escape(task_id)}</span></div></td>"
                f"<td>{html.escape(str((task.get('payload') or {}).get('type') if isinstance(task.get('payload'), dict) else ''))}</td>"
                f"<td>{html.escape(str(task.get('state') or ''))}</td>"
                f"<td>{html.escape(str(task.get('error_code') or ''))}</td>"
                f"<td><pre>{html.escape(_pretty(task.get('payload') or {}))}</pre></td>"
                "</tr>"
            )
    task_graph_html = (
        "<section class='panel sand'>"
        "<h2>PA Task Graph</h2>"
        "<div class='table-wrap'><table><thead><tr><th>Task</th><th>Type</th><th>State</th><th>Error</th><th>Payload</th></tr></thead>"
        f"<tbody>{''.join(task_rows) if task_rows else '<tr><td colspan=\"5\" class=\"empty-cell\">No task graph</td></tr>'}</tbody>"
        "</table></div></section>"
    )

    task_exec_items = pa.get("task_executions") or []
    task_exec_cards = []
    for item in task_exec_items if isinstance(task_exec_items, list) else []:
        task_id = str(item.get("task_id") or "").strip()
        task_exec_cards.append(
            f"<details class='item-card filterable trace-record task-exec-record' id='{html.escape(_dom_id('task-exec', task_id))}' data-task-ids='{html.escape(task_id)}'>"
            "<summary>"
            f"<div class='summary-head'><span class='chip'>{html.escape(str(item.get('task_id') or ''))}</span>"
            f"<span class='chip'>{html.escape(str(item.get('task_type') or ''))}</span>"
            f"<span class='chip muted'>{html.escape(str(item.get('idempotency_key') or ''))}</span></div>"
            "</summary>"
            f"<pre>{html.escape(_pretty(item.get('record') or {}))}</pre>"
            "</details>"
        )
    task_exec_html = (
        "<section class='panel rust'>"
        "<h2>Task Executions</h2>"
        f"{''.join(task_exec_cards) if task_exec_cards else '<p class=\"empty\">No task executions</p>'}"
        "</section>"
    )

    runtime_task_bundle = dict(runtime_debug.get("task_bundle") or {}) if isinstance(runtime_debug, dict) else {}
    runtime_execution_policy = (
        dict(runtime_debug.get("task_execution_policy") or {})
        if isinstance(runtime_debug, dict)
        else {}
    )
    runtime_file_refs = list(runtime_debug.get("file_refs") or []) if isinstance(runtime_debug, dict) else []
    runtime_context_chain = dict(runtime_debug.get("context_chain") or {}) if isinstance(runtime_debug, dict) else {}
    leader_rail_items = list(runtime_debug.get("leader_rail") or []) if isinstance(runtime_debug, dict) else []
    plan_revision_items = list(runtime_debug.get("plan_revisions") or []) if isinstance(runtime_debug, dict) else []
    result_capsule_items = list(runtime_debug.get("result_capsules") or []) if isinstance(runtime_debug, dict) else []
    retry_timeout_events = list(runtime_debug.get("retry_timeout_events") or []) if isinstance(runtime_debug, dict) else []
    leader_rail_html = (
        "<section class='panel navy'><h2>Leader Rail</h2>"
        + (
            "".join(
                "<div class='item-card'>"
                f"<div class='summary-head'><span class='chip'>{html.escape(str(item.get('phase') or ''))}</span>"
                f"<span class='chip muted'>{html.escape(str(item.get('status') or 'missing'))}</span>"
                f"<span class='chip'>{int(item.get('deadline_ms') or 0)} ms</span></div>"
                + (f"<p class='mini'>{html.escape(str(item.get('error_code') or ''))}</p>" if str(item.get("error_code") or "").strip() else "")
                + "</div>"
                for item in leader_rail_items
                if isinstance(item, dict)
            )
            or "<p class='empty'>No leader phase records</p>"
        )
        + "</section>"
    )
    task_bundle_panel_html = (
        "<section class='panel sand'><h2>Task Bundle</h2>"
        + (
            _render_runtime_pairs(
                [
                    ("objective", runtime_task_bundle.get("objective") or ""),
                    ("task_mode", runtime_task_bundle.get("task_mode") or ""),
                    ("worker_task_admission_mode", runtime_task_bundle.get("worker_task_admission_mode") or ""),
                    ("delegation_budget", runtime_task_bundle.get("delegation_budget") or 0),
                    ("max_depth", runtime_task_bundle.get("max_depth") or 0),
                    ("sufficient_for_execution", runtime_task_bundle.get("sufficient_for_execution")),
                ]
            )
            if runtime_task_bundle
            else "<p class='empty'>No task bundle</p>"
        )
        + "</section>"
    )
    file_refs_panel_html = f"<section class='panel sand'><h2>File Refs</h2>{_render_file_refs([dict(item) for item in runtime_file_refs if isinstance(item, dict)])}</section>"
    execution_policy_html = (
        "<section class='panel slate'><h2>Execution Policy</h2>"
        + (
            _render_runtime_pairs(
                [
                    ("llm_timeout_ms", runtime_execution_policy.get("llm_timeout_ms") or 0),
                    ("tool_timeout_ms", runtime_execution_policy.get("tool_timeout_ms") or 0),
                    ("max_attempts", runtime_execution_policy.get("max_attempts") or 0),
                    ("side_effect_safe_retry", runtime_execution_policy.get("side_effect_safe_retry")),
                    ("tool_retry_policy", runtime_execution_policy.get("tool_retry_policy") or {}),
                ]
            )
            if runtime_execution_policy
            else "<p class='empty'>No execution policy</p>"
        )
        + "</section>"
    )
    context_chain_html = (
        "<section class='panel slate'><h2>Context Chain</h2>"
        + _render_runtime_pairs(
            [
                ("context_snapshot_ref", runtime_context_chain.get("context_snapshot_ref") or ""),
                ("bundle_sufficient_for_execution", runtime_context_chain.get("bundle_sufficient_for_execution")),
                ("context_escalation_mode", runtime_context_chain.get("context_escalation_mode") or ""),
                ("worker_task_admission_mode", runtime_context_chain.get("worker_task_admission_mode") or ""),
                ("read_only_ancestor_context_refs", runtime_context_chain.get("read_only_ancestor_context_refs") or []),
            ]
        )
        + "</section>"
    )
    plan_revisions_html = (
        "<section class='panel navy'><h2>Plan Revisions</h2>"
        + (
            "".join(
                "<details class='item-card' open>"
                f"<summary><div class='summary-head'><span class='chip'>rev {int(item.get('plan_revision') or 0)}</span>"
                f"<span class='chip muted'>{html.escape(str(item.get('planner_status') or item.get('status') or ''))}</span>"
                f"<span class='chip'>{int(item.get('action_count') or 0)} actions</span></div></summary>"
                f"<pre>{html.escape(_pretty(item))}</pre>"
                "</details>"
                for item in plan_revision_items
                if isinstance(item, dict)
            )
            or "<p class='empty'>No recorded plan revisions</p>"
        )
        + "</section>"
    )
    result_capsules_html = (
        "<section class='panel rust'><h2>Result Capsules</h2>"
        + (
            "".join(
                "<details class='item-card' open>"
                f"<summary><div class='summary-head'><span class='chip'>{html.escape(str(item.get('task_id') or ''))}</span>"
                f"<span class='chip muted'>{html.escape(str(item.get('status') or ''))}</span>"
                f"<span class='chip'>{html.escape(str(item.get('operator_ref') or item.get('delivery_state') or ''))}</span></div></summary>"
                f"<pre>{html.escape(_pretty(item))}</pre>"
                "</details>"
                for item in result_capsule_items
                if isinstance(item, dict)
            )
            or "<p class='empty'>No result capsules</p>"
        )
        + "</section>"
    )
    retry_timeout_html = (
        "<section class='panel rust'><h2>Retry & Timeout</h2>"
        + (
            "".join(
                "<details class='item-card' open>"
                f"<summary><div class='summary-head'><span class='chip'>{html.escape(str(item.get('phase') or ''))}</span>"
                f"<span class='chip muted'>{html.escape(str(item.get('status') or ''))}</span>"
                f"<span class='chip'>{int(item.get('deadline_ms') or 0)} ms</span></div></summary>"
                f"<pre>{html.escape(_pretty(item))}</pre>"
                "</details>"
                for item in retry_timeout_events
                if isinstance(item, dict)
            )
            or "<p class='empty'>No retry/timeout events</p>"
        )
        + "</section>"
    )

    prompt_refs = prompt_assembly.get("prompt_refs") or []
    context_refs = prompt_assembly.get("context_refs") or []
    policy_refs = prompt_assembly.get("policy_refs") or []
    tool_refs = prompt_assembly.get("tool_io_refs") or []
    assembly_html = (
        "<section class='panel slate'>"
        "<h2>Prompt Assembly</h2>"
        "<div class='chips-block'>"
        + "".join(f"<span class='chip'>{html.escape(str(ref))}</span>" for ref in prompt_refs)
        + "</div>"
        "<p class='mini'>Context refs</p><div class='chips-block'>"
        + "".join(f"<span class='chip muted'>{html.escape(str(ref))}</span>" for ref in context_refs)
        + "</div>"
        "<p class='mini'>Tool refs</p><div class='chips-block'>"
        + "".join(f"<span class='chip muted'>{html.escape(str(ref))}</span>" for ref in tool_refs)
        + "</div>"
        "<p class='mini'>Policy refs</p><div class='chips-block'>"
        + "".join(f"<span class='chip muted'>{html.escape(str(ref))}</span>" for ref in policy_refs)
        + "</div>"
        "</section>"
    )

    overview_cards = [
        ("Trace Events", str(summary.get("trace_event_count") or 0)),
        ("Prompts", str(summary.get("prompt_count") or 0)),
        ("LLM Outputs", str(summary.get("llm_output_count") or 0)),
        ("Errors", str(summary.get("error_count") or 0)),
        ("Task Execs", str(summary.get("task_execution_count") or 0)),
    ]
    overview_html = "".join(
        f"<div class='metric'><div class='metric-label'>{html.escape(label)}</div><div class='metric-value'>{html.escape(value)}</div></div>"
        for label, value in overview_cards
    )

    task_options = ["<option value=''>All tasks / steps</option>"]
    for item in task_focus_items:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("task_id") or "").strip()
        label_bits = [task_id]
        if item.get("task_type"):
            label_bits.append(str(item.get("task_type") or ""))
        if item.get("state"):
            label_bits.append(str(item.get("state") or ""))
        if item.get("refs"):
            label_bits.append(f"{len(item.get('refs') or [])} refs")
        task_options.append(
            f"<option value='{html.escape(task_id)}'>{html.escape(' · '.join(label_bits))}</option>"
        )
    filter_html = (
        "<section class='panel slate'>"
        "<h2>Trace Filters</h2>"
        "<div class='filter-row'>"
        "<label class='filter-label' for='task-filter'>Task / Step</label>"
        f"<select id='task-filter' class='filter-select'>{''.join(task_options)}</select>"
        "<button id='task-filter-reset' class='mini-button' type='button'>Reset</button>"
        "</div>"
        "<p class='mini'>点击 DAG 节点或 Focus 按钮，会同步筛选 prompt / context / output / task execution。</p>"
        "</section>"
    )

    raw_pa_blocks = []
    for label in ("event", "outbox"):
        payload = pa.get(label)
        raw_pa_blocks.append(
            "<details class='item-card'>"
            f"<summary><div class='summary-head'><span class='chip'>{html.escape(label)}</span></div></summary>"
            f"<pre>{html.escape(_pretty(payload))}</pre>"
            "</details>"
        )
    raw_pa_html = f"<section class='panel slate'><h2>PA Records</h2>{''.join(raw_pa_blocks)}</section>"

    session_entries_html = ""
    if isinstance(session, dict) and isinstance(session.get("entries"), list) and session.get("entries"):
        links = []
        for item in session.get("entries") or []:
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("event_id") or "").strip()
            workspace_id = str(item.get("workspace_id") or "").strip()
            trace_id = str(item.get("trace_id") or "").strip()
            title_text = str(item.get("title") or event_id or trace_id).strip()
            href = "/trace?" + urlencode(
                {k: v for k, v in {"event_id": event_id, "workspace_id": workspace_id, "trace_id": trace_id}.items() if str(v).strip()}
            )
            links.append(
                f"<a class='session-link' href='{html.escape(href)}'>{html.escape(title_text)}</a>"
            )
        session_entries_html = (
            "<section class='panel sand'>"
            "<h2>Session Turns</h2>"
            f"<div class='session-links'>{''.join(links)}</div>"
            "</section>"
        )

    task_focus_payload = {
        str(item.get("task_id") or ""): {
            "task_id": str(item.get("task_id") or ""),
            "task_type": str(item.get("task_type") or ""),
            "state": str(item.get("state") or ""),
            "error_code": str(item.get("error_code") or ""),
            "refs": [
                {
                    "ref": ref,
                    "anchor": _dom_id("evidence", ref),
                }
                for ref in list(item.get("refs") or [])
            ],
            "execution_anchor": str(item.get("execution_anchor") or ""),
            "task_bundle": dict(item.get("task_bundle") or {}) if isinstance(item.get("task_bundle"), dict) else {},
            "file_refs": [dict(ref) for ref in (item.get("file_refs") or []) if isinstance(ref, dict)],
            "task_execution_policy": (
                dict(item.get("task_execution_policy") or {})
                if isinstance(item.get("task_execution_policy"), dict)
                else {}
            ),
            "context_snapshot_ref": str(item.get("context_snapshot_ref") or ""),
            "read_only_ancestor_context_refs": list(item.get("read_only_ancestor_context_refs") or []),
            "bundle_sufficient_for_execution": item.get("bundle_sufficient_for_execution"),
            "result_capsule_ids": list(item.get("result_capsule_ids") or []),
        }
        for item in task_focus_items
        if isinstance(item, dict)
    }

    body = (
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(title)}</title>"
        "<style>"
        ":root{--bg:#f5f1e8;--paper:#fffdf8;--ink:#1c2430;--muted:#5e6a78;--line:#d7cfbf;--accent:#16324f;--accent-2:#8a3b12;--good:#1c6b3f;--bad:#9b2c2c;}"
        "*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#ede6d8 0%,#f7f4ed 100%);color:var(--ink);font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}"
        ".page{max-width:1440px;margin:0 auto;padding:28px 24px 48px}"
        ".hero{display:grid;grid-template-columns:1.5fr 1fr;gap:18px;align-items:start;margin-bottom:20px}"
        ".title{background:var(--accent);color:#f9f4eb;border-radius:22px;padding:24px 26px;box-shadow:0 16px 40px rgba(22,50,79,.18)}"
        ".title h1{margin:0;font-size:28px;letter-spacing:.02em}.title p{margin:10px 0 0;color:#d8e1ea}"
        ".status{background:var(--paper);border:1px solid var(--line);border-radius:22px;padding:24px;box-shadow:0 10px 26px rgba(28,36,48,.08)}"
        ".status-badge{display:inline-block;padding:6px 10px;border-radius:999px;background:#efe6d8;color:var(--accent-2);font-weight:700;font-size:12px;letter-spacing:.06em}"
        ".metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:18px 0 20px}"
        ".metric{background:var(--paper);border:1px solid var(--line);border-radius:18px;padding:14px 16px;min-height:92px}.metric-label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}.metric-value{font-size:30px;font-weight:800;margin-top:8px}"
        ".grid{display:grid;grid-template-columns:1.05fr .95fr;gap:18px}.stack{display:grid;gap:18px}"
        ".panel{background:var(--paper);border:1px solid var(--line);border-radius:22px;padding:20px;box-shadow:0 10px 24px rgba(28,36,48,.06)}"
        ".panel h2{margin:0 0 14px;font-size:16px;letter-spacing:.03em;text-transform:uppercase}.panel.navy h2{color:var(--accent)}.panel.rust h2{color:var(--accent-2)}.panel.rose h2{color:var(--bad)}.panel.sand h2,.panel.slate h2{color:var(--ink)}"
        ".chip{display:inline-flex;align-items:center;padding:4px 10px;border-radius:999px;background:#e8ecef;color:var(--accent);margin:0 6px 6px 0;font-size:12px;font-weight:700;word-break:break-all}.chip.muted{background:#efe7da;color:var(--muted)}.task-chip{background:#dce7f2;color:#16324f}"
        ".chips-block{margin-bottom:10px}.mini{margin:12px 0 6px;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}"
        ".item-card{border:1px solid var(--line);border-radius:16px;padding:10px 12px;margin-bottom:12px;background:#fffdfa}.item-card summary{cursor:pointer;list-style:none}.item-card summary::-webkit-details-marker{display:none}.summary-head{display:flex;flex-wrap:wrap;gap:6px;align-items:center}"
        ".sources{margin:10px 0 6px}pre{margin:0;white-space:pre-wrap;word-break:break-word;background:#181f27;color:#eef3f7;border-radius:14px;padding:14px;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;overflow:auto}"
        "pre.diff span{display:block}.diff-add{background:rgba(22,107,63,.28)}.diff-del{background:rgba(155,44,44,.28)}.diff-hdr{color:#f6d48f}.diff-ctx{color:#eef3f7}"
        ".table-wrap{overflow:auto}table{width:100%;border-collapse:collapse}th,td{vertical-align:top;border-top:1px solid var(--line);padding:10px 8px;text-align:left}th{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}td{font-size:13px}.event{font-weight:700;color:var(--accent)}"
        ".empty,.empty-cell{color:var(--muted)}.session-links{display:flex;flex-wrap:wrap;gap:10px}.session-link{display:inline-flex;align-items:center;padding:8px 12px;border-radius:999px;background:#ece5d9;color:var(--accent);text-decoration:none;font-weight:700}"
        ".filter-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.filter-label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;font-weight:700}.filter-select{min-width:280px;border:1px solid var(--line);border-radius:12px;background:#fffdfa;padding:10px 12px;color:var(--ink);font-size:14px}"
        ".mini-button{border:1px solid var(--line);background:#ece5d9;color:var(--accent);padding:8px 12px;border-radius:999px;font-weight:700;cursor:pointer}.mini-button:hover{background:#e4dbc9}"
        ".task-cell{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.trace-record.is-focused-record,.task-row.is-focused-record{border-color:#16324f;box-shadow:0 0 0 2px rgba(22,50,79,.12)}"
        ".kv-row{display:grid;grid-template-columns:180px 1fr;gap:12px;padding:8px 0;border-top:1px solid var(--line)}.kv-row:first-child{border-top:none;padding-top:0}.kv-label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}.kv-value{font-size:13px;word-break:break-word}"
        ".dag-layout{display:grid;grid-template-columns:1.2fr .8fr;gap:16px;align-items:start}.dag-shell{border:1px solid var(--line);border-radius:18px;background:#fcfaf4;padding:10px;overflow:auto}.dag-hint{margin:0 0 12px;color:var(--muted);font-size:13px}.dag-node{cursor:pointer;transition:transform .15s ease,opacity .15s ease}.dag-node:hover{transform:translateY(-2px)}.dag-node.active rect{stroke:#16324f;stroke-width:4;opacity:.28}.dag-node.active text{font-weight:800}.dag-inspector{border:1px solid var(--line);border-radius:18px;background:#fffdfa;padding:16px;min-height:180px}.dag-inspector h3{margin:0 0 8px;font-size:15px}.dag-inspector p{margin:6px 0 0;color:var(--muted);font-size:13px}.dag-links{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}"
        "@media (max-width:1080px){.hero,.grid{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}"
        "@media (max-width:1080px){.dag-layout{grid-template-columns:1fr}}"
        "</style></head><body><div class='page'>"
        f"<section class='hero'><div class='title'><h1>{html.escape(title)}</h1><p>{html.escape(str(resolved.get('trace_id') or requested.get('event_id') or ''))}</p></div>"
        f"<div class='status'><span class='status-badge'>{html.escape(status_text)}</span><p><strong>Trace</strong>: {html.escape(str(resolved.get('trace_id') or ''))}</p><p><strong>Turn</strong>: {html.escape(str(resolved.get('turn_id') or ''))}</p><p><strong>Event</strong>: {html.escape(str(requested.get('event_id') or ''))}</p></div></section>"
        f"<section class='metrics'>{overview_html}</section>"
        f"{filter_html}"
        "<section class='grid'>"
        "<div class='stack'>"
        f"{leader_rail_html}"
        f"{task_bundle_panel_html}"
        f"{file_refs_panel_html}"
        f"{assembly_html}"
        f"{_render_evidence_group('Prompts', list(evidence.get('prompts') or []), 'navy')}"
        f"{_render_diff_group('Prompt Diffs', list(evidence.get('prompts') or []))}"
        f"{_render_evidence_group('LLM Outputs', list(evidence.get('llm_outputs') or []), 'sand')}"
        f"{_render_diff_group('Output Diffs', list(evidence.get('llm_outputs') or []))}"
        f"{_render_evidence_group('Errors', list(evidence.get('errors') or []), 'rose')}"
        f"{timeline_html}"
        "</div>"
        "<div class='stack'>"
        f"{execution_policy_html}"
        f"{context_chain_html}"
        f"{plan_revisions_html}"
        f"{result_capsules_html}"
        f"{retry_timeout_html}"
        f"{_render_evidence_group('Context', list(evidence.get('context') or []), 'slate')}"
        f"{_render_diff_group('Context Diffs', list(evidence.get('context') or []))}"
        f"{_render_evidence_group('Tool IO', list(evidence.get('tool_io') or []), 'sand')}"
        f"{_render_evidence_group('Policies', list(evidence.get('policies') or []), 'slate')}"
        f"{session_entries_html}"
        f"{task_graph_html}"
        f"{_render_task_graph_svg(task_graph, task_focus_items)}"
        f"{task_exec_html}"
        f"{raw_pa_html}"
        "</div>"
        "</section>"
        "<script>"
        f"const taskIndex={_script_json(task_focus_payload)};"
        "const taskFilter=document.getElementById('task-filter');"
        "const resetFilter=document.getElementById('task-filter-reset');"
        "const inspector=document.getElementById('dag-inspector');"
        "const filterables=[...document.querySelectorAll('.filterable')];"
        "const dagNodes=[...document.querySelectorAll('.dag-node')];"
        "const focusTriggers=[...document.querySelectorAll('[data-task-focus]')];"
        "const esc=(value)=>String(value||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('\"','&quot;').replaceAll(\"'\",'&#39;');"
        "const tokens=(el)=>String(el.dataset.taskIds||'').split(/\\s+/).filter(Boolean);"
        "function renderInspector(taskId){if(!inspector){return;} if(!taskId||!taskIndex[taskId]){inspector.innerHTML=\"<h3>Task Inspector</h3><p>点击 DAG 节点或 Focus 按钮，右侧会联动相关 evidence、diff 和 task execution。</p>\";return;} const item=taskIndex[taskId]; const refs=(item.refs||[]).map((entry)=>`<a class='session-link' href='#${esc(entry.anchor)}'>${esc(entry.ref)}</a>`).join(''); const execLink=item.execution_anchor?`<a class='session-link' href='#${esc(item.execution_anchor)}'>task execution</a>`:''; const bundle=item.task_bundle||{}; const policy=item.task_execution_policy||{}; const fileRefs=(item.file_refs||[]).length; const contextRefs=(item.read_only_ancestor_context_refs||[]).join(', '); const capsuleIds=(item.result_capsule_ids||[]).join(', '); inspector.innerHTML=`<h3>${esc(item.task_id)}</h3><p>${esc(item.task_type||'task')} · ${esc(item.state||'unknown')}</p><p>${esc(item.error_code||'')}</p><p>bundle sufficient: ${esc(String(item.bundle_sufficient_for_execution))}</p><p>context snapshot: ${esc(item.context_snapshot_ref||'')}</p><p>file refs: ${esc(String(fileRefs))}</p><p>policy: llm=${esc(String(policy.llm_timeout_ms||''))} tool=${esc(String(policy.tool_timeout_ms||''))}</p><p>result capsules: ${esc(capsuleIds)}</p><p>${esc(contextRefs)}</p><div class='dag-links'>${execLink}${refs}</div><pre>${esc(JSON.stringify(bundle,null,2))}</pre>`;}"
        "function applyTaskFocus(taskId){const active=(taskId&&taskIndex[taskId])?taskId:''; if(taskFilter&&taskFilter.value!==active){taskFilter.value=active;} for(const el of filterables){const visible=!active||tokens(el).includes(active); el.style.display=visible?'':'none'; el.classList.toggle('is-focused-record',!!active&&visible);} for(const node of dagNodes){node.classList.toggle('active',!!active&&node.dataset.taskFocus===active);} renderInspector(active);}"
        "if(taskFilter){taskFilter.addEventListener('change',()=>applyTaskFocus(taskFilter.value));}"
        "if(resetFilter){resetFilter.addEventListener('click',()=>applyTaskFocus(''));}"
        "for(const trigger of focusTriggers){trigger.addEventListener('click',(event)=>{event.preventDefault(); const taskId=trigger.dataset.taskFocus||''; applyTaskFocus(taskId); const target=document.querySelector(`.filterable[data-task-ids~=\"${taskId}\"]`); if(target){target.scrollIntoView({behavior:'smooth',block:'nearest'});}}); if(trigger.classList.contains('dag-node')){trigger.addEventListener('keydown',(event)=>{if(event.key==='Enter'||event.key===' '){event.preventDefault(); trigger.click();}});}}"
        "renderInspector('');"
        "</script>"
        "</div></body></html>"
    )
    return body


def _render_task_graph_svg(task_graph: Any, task_focus_items: list[dict[str, Any]]) -> str:
    if not isinstance(task_graph, dict) or not isinstance(task_graph.get("tasks"), list):
        return "<section class='panel slate'><h2>Execution DAG</h2><p class='empty'>No task graph.</p></section>"

    tasks = [task for task in task_graph.get("tasks") or [] if isinstance(task, dict)]
    if not tasks:
        return "<section class='panel slate'><h2>Execution DAG</h2><p class='empty'>No task graph.</p></section>"

    focus_map = {
        str(item.get("task_id") or ""): item
        for item in task_focus_items
        if isinstance(item, dict) and str(item.get("task_id") or "").strip()
    }
    by_id = {str(task.get("task_id") or ""): task for task in tasks}
    children: dict[str, list[str]] = {}
    depths: dict[str, int] = {}

    def _depth(task_id: str) -> int:
        if task_id in depths:
            return depths[task_id]
        task = by_id.get(task_id) or {}
        parent = str(task.get("parent_task_id") or "").strip()
        depths[task_id] = 0 if not parent else _depth(parent) + 1
        return depths[task_id]

    for task in tasks:
        task_id = str(task.get("task_id") or "")
        parent = str(task.get("parent_task_id") or "").strip()
        _depth(task_id)
        if parent:
            children.setdefault(parent, []).append(task_id)

    levels: dict[int, list[dict[str, Any]]] = {}
    for task in sorted(tasks, key=lambda item: (int(item.get("seq") or 0), str(item.get("task_id") or ""))):
        levels.setdefault(_depth(str(task.get("task_id") or "")), []).append(task)

    positions: dict[str, tuple[int, int]] = {}
    max_level = max(levels.keys()) if levels else 0
    max_rows = 1
    for level, group in levels.items():
        max_rows = max(max_rows, len(group))
        for idx, task in enumerate(group):
            positions[str(task.get("task_id") or "")] = (120 + level * 240, 80 + idx * 118)

    width = 240 + max_level * 240
    height = 160 + max_rows * 118
    colors = {
        "queued": "#d5b15a",
        "running": "#4c88bf",
        "succeeded": "#2b8a57",
        "failed": "#b94b4b",
    }

    edges = []
    for task in tasks:
        task_id = str(task.get("task_id") or "")
        parent = str(task.get("parent_task_id") or "").strip()
        if not parent or parent not in positions or task_id not in positions:
            continue
        x1, y1 = positions[parent]
        x2, y2 = positions[task_id]
        edges.append(
            f"<path d='M {x1+86} {y1} C {x1+150} {y1}, {x2-150} {y2}, {x2-86} {y2}' stroke='#7b8794' stroke-width='2.4' fill='none' marker-end='url(#arrow)'/>"
        )

    nodes = []
    for task in tasks:
        task_id = str(task.get("task_id") or "")
        x, y = positions[task_id]
        state = str(task.get("state") or "")
        color = colors.get(state, "#7b8794")
        payload = task.get("payload") or {}
        task_type = str(payload.get("type") if isinstance(payload, dict) else "") or "task"
        error_code = str(task.get("error_code") or "").strip()
        ref_count = len((focus_map.get(task_id) or {}).get("refs") or [])
        lines = [task_id, task_type, state]
        if error_code:
            lines.append(error_code[:22])
        tspan = "".join(
            f"<tspan x='{x}' dy='{16 if idx else 0}'>{html.escape(line)}</tspan>"
            for idx, line in enumerate(lines)
        )
        nodes.append(
            f"<g class='dag-node' tabindex='0' role='button' data-task-focus='{html.escape(task_id)}'>"
            f"<title>{html.escape(task_id)} · {html.escape(task_type)} · {html.escape(state)} · {ref_count} refs</title>"
            f"<rect x='{x-86}' y='{y-34}' rx='18' ry='18' width='172' height='72' fill='{color}' opacity='0.18' stroke='{color}' stroke-width='2.5'/>"
            f"<text x='{x}' y='{y-10}' text-anchor='middle' font-size='12.5' font-family='ui-sans-serif,system-ui' fill='#14202b'>{tspan}</text>"
            "</g>"
        )

    svg = (
        "<section class='panel slate'><h2>Execution DAG</h2><p class='dag-hint'>点击节点会聚焦对应 task 的 evidence、diff 和执行记录。</p><div class='dag-layout'>"
        f"<div class='dag-shell'><svg viewBox='0 0 {width} {height}' width='100%' role='img'>"
        "<defs><marker id='arrow' markerWidth='10' markerHeight='8' refX='9' refY='4' orient='auto'><path d='M0,0 L10,4 L0,8 z' fill='#7b8794'/></marker></defs>"
        + "".join(edges)
        + "".join(nodes)
        + "</svg></div><aside id='dag-inspector' class='dag-inspector'><h3>Task Inspector</h3><p>点击 DAG 节点或 Focus 按钮，右侧会联动相关 evidence、diff 和 task execution。</p></aside></div></section>"
    )
    return svg


def _catalog_guess_trace_id(*, data_dir: Path, event_id: str, outbox_obj: Any) -> str:
    if isinstance(outbox_obj, dict):
        trace = outbox_obj.get("trace")
        if isinstance(trace, dict):
            trace_id = str(trace.get("trace_id") or "").strip()
            if trace_id:
                return trace_id
    guessed = f"tr_pa_{event_id}"
    return guessed if _trace_path(data_dir, guessed).exists() else ""


def build_trace_catalog(*, data_dir: str | Path = "data", limit: int = 100) -> dict[str, Any]:
    base = Path(data_dir)
    entries: list[dict[str, Any]] = []
    seen_trace_ids: set[str] = set()
    sessions_by_key: dict[str, dict[str, Any]] = {}

    events_root = base / "pa" / "events"
    if events_root.exists():
        for path in sorted(events_root.glob("*/*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            obj = _safe_read_json(path)
            if not isinstance(obj, dict):
                continue
            workspace_id = str(obj.get("workspace_id") or path.parent.name)
            event_id = str(obj.get("event_id") or path.stem)
            envelope = obj.get("envelope") or {}
            message_text = ""
            if isinstance(envelope, dict):
                message_text = str(envelope.get("message_text") or "").strip()
            conversation_id = str(envelope.get("conversation_id") or "").strip() if isinstance(envelope, dict) else ""
            outbox_obj = _safe_read_json(_outbox_path(base, workspace_id, event_id))
            trace_id = _catalog_guess_trace_id(data_dir=base, event_id=event_id, outbox_obj=outbox_obj)
            if trace_id:
                seen_trace_ids.add(trace_id)
            execute = outbox_obj.get("execute") if isinstance(outbox_obj, dict) else {}
            status = str(execute.get("status") or "pending") if isinstance(execute, dict) else "pending"
            error_code = str(execute.get("error_code") or "") if isinstance(execute, dict) else ""
            reply_text = str(outbox_obj.get("reply_text") or "").strip() if isinstance(outbox_obj, dict) else ""
            entries.append(
                {
                    "kind": "pa_event",
                    "event_id": event_id,
                    "workspace_id": workspace_id,
                    "trace_id": trace_id,
                    "turn_id": str(((outbox_obj or {}).get("trace") or {}).get("turn_id") or "") if isinstance(outbox_obj, dict) else "",
                    "conversation_id": conversation_id,
                    "title": message_text or event_id,
                    "subtitle": reply_text[:180],
                    "status": status,
                    "error_code": error_code,
                    "stored_at": str(obj.get("stored_at_utc") or ""),
                    "link_query": {"event_id": event_id, "workspace_id": workspace_id},
                }
            )
            session_key = f"{workspace_id}:{conversation_id or trace_id or event_id}"
            session = sessions_by_key.setdefault(
                session_key,
                {
                    "session_id": session_key,
                    "workspace_id": workspace_id,
                    "conversation_id": conversation_id,
                    "entry_count": 0,
                    "entries": [],
                },
            )
            session["entries"].append(entries[-1])
            session["entry_count"] = int(session.get("entry_count") or 0) + 1

    traces_root = base / "traces"
    if traces_root.exists():
        for path in sorted(traces_root.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            trace_id = path.stem
            if trace_id in seen_trace_ids:
                continue
            first_line = ""
            try:
                with path.open("r", encoding="utf-8") as f:
                    for raw in f:
                        if raw.strip():
                            first_line = raw.strip()
                            break
            except Exception:
                first_line = ""
            event_type = ""
            if first_line:
                obj = _safe_read_json(path)  # intentionally None; file is jsonl not json
                _ = obj
                try:
                    first_obj = json.loads(first_line)
                    if isinstance(first_obj, dict):
                        event_type = str(first_obj.get("event_type") or "")
                except Exception:
                    event_type = ""
            entries.append(
                {
                    "kind": "trace",
                    "event_id": "",
                    "workspace_id": "",
                    "trace_id": trace_id,
                    "turn_id": "",
                    "title": trace_id,
                    "subtitle": event_type or "trace only",
                    "status": "trace",
                    "error_code": "",
                    "stored_at": "",
                    "link_query": {"trace_id": trace_id},
                }
            )
            session_key = f"trace:{trace_id}"
            sessions_by_key[session_key] = {
                "session_id": session_key,
                "workspace_id": "",
                "conversation_id": "",
                "entry_count": 1,
                "entries": [entries[-1]],
            }

    entries.sort(key=lambda item: (str(item.get("stored_at") or ""), str(item.get("trace_id") or item.get("event_id") or "")), reverse=True)
    trimmed = entries[: max(1, int(limit))]
    sessions: list[dict[str, Any]] = []
    for session in sessions_by_key.values():
        session_entries = sorted(
            list(session.get("entries") or []),
            key=lambda item: (str(item.get("stored_at") or ""), str(item.get("trace_id") or item.get("event_id") or "")),
            reverse=True,
        )
        latest = session_entries[0] if session_entries else {}
        sessions.append(
            {
                "session_id": str(session.get("session_id") or ""),
                "workspace_id": str(session.get("workspace_id") or ""),
                "conversation_id": str(session.get("conversation_id") or ""),
                "entry_count": int(session.get("entry_count") or 0),
                "title": str(latest.get("title") or latest.get("trace_id") or latest.get("event_id") or ""),
                "subtitle": str(latest.get("subtitle") or ""),
                "latest_status": str(latest.get("status") or ""),
                "latest_error_code": str(latest.get("error_code") or ""),
                "latest_link_query": dict(latest.get("link_query") or {}),
                "entries": session_entries[:20],
            }
        )
    sessions.sort(key=lambda item: str(((item.get("entries") or [{}])[0]).get("stored_at") or ""), reverse=True)
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "data_dir": str(base),
        "count": len(trimmed),
        "items": trimmed,
        "session_count": len(sessions),
        "sessions": sessions[: max(1, int(limit))],
    }


def render_trace_catalog_html(catalog: dict[str, Any], *, selected_session_id: str | None = None) -> str:
    sessions = catalog.get("sessions") or []
    count = int(catalog.get("count") or 0)
    session_count = int(catalog.get("session_count") or 0)
    session_items = [dict(session) for session in sessions if isinstance(sessions, list) and isinstance(session, dict)]
    active_session = None
    selected = str(selected_session_id or "").strip()
    if selected:
        for session in session_items:
            if str(session.get("session_id") or "").strip() == selected:
                active_session = session
                break
    if active_session is None and session_items:
        active_session = session_items[0]

    cards = []
    for session in session_items:
        if not isinstance(session, dict):
            continue
        href = "/?" + urlencode({"session_id": str(session.get("session_id") or "")})
        subtitle = str(session.get("subtitle") or "").strip()
        error_code = str(session.get("latest_error_code") or "").strip()
        meta_bits = [
            "<span class='chip'>session</span>",
            f"<span class='chip'>{html.escape(str(session.get('latest_status') or ''))}</span>",
            f"<span class='chip muted'>{int(session.get('entry_count') or 0)} turns</span>",
        ]
        if session.get("workspace_id"):
            meta_bits.append(f"<span class='chip muted'>{html.escape(str(session.get('workspace_id') or ''))}</span>")
        if session.get("conversation_id"):
            meta_bits.append(f"<span class='chip muted'>{html.escape(str(session.get('conversation_id') or ''))}</span>")
        if error_code:
            meta_bits.append(f"<span class='chip error'>{html.escape(error_code)}</span>")
        entry_links = []
        for entry in session.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            entry_query = entry.get("link_query") or {}
            entry_href = "/trace?" + urlencode({k: v for k, v in entry_query.items() if str(v or "").strip()})
            entry_label = str(entry.get("event_id") or entry.get("trace_id") or "entry")
            entry_links.append(f"<a class='mini-link' href='{html.escape(entry_href)}'>{html.escape(entry_label)}</a>")
        is_active = active_session is not None and str(active_session.get("session_id") or "") == str(session.get("session_id") or "")
        cards.append(
            "<div class='card" + (" active" if is_active else "") + "' data-search='" + html.escape(
                " ".join(
                    [str(session.get(key) or "") for key in ("title", "subtitle", "workspace_id", "conversation_id", "latest_status", "latest_error_code", "session_id")]
                    + [
                        " ".join(
                            str(entry.get(key) or "")
                            for key in ("event_id", "trace_id", "title", "subtitle")
                        )
                        for entry in (session.get("entries") or [])
                        if isinstance(entry, dict)
                    ]
                ).lower()
            ) + "'>"
            f"<a class='card-main-link' href='{html.escape(href)}'><div class='card-title'>{html.escape(str(session.get('title') or ''))}</div></a>"
            f"<div class='card-meta'>{''.join(meta_bits)}</div>"
            f"<div class='card-subtitle'>{html.escape(subtitle or 'No subtitle')}</div>"
            f"<div class='card-links'>{''.join(entry_links[:4])}</div>"
            "</div>"
        )

    transcript_cards = []
    active_entries = list(active_session.get("entries") or []) if isinstance(active_session, dict) else []
    active_entries = sorted(
        [dict(item) for item in active_entries if isinstance(item, dict)],
        key=lambda item: (str(item.get("stored_at") or ""), str(item.get("trace_id") or item.get("event_id") or "")),
    )
    for entry in active_entries:
        entry_query = entry.get("link_query") or {}
        entry_href = "/trace?" + urlencode({k: v for k, v in entry_query.items() if str(v or "").strip()})
        entry_status = html.escape(str(entry.get("status") or ""))
        entry_title = html.escape(str(entry.get("title") or ""))
        entry_subtitle = html.escape(str(entry.get("subtitle") or "No reply"))
        entry_error_code = str(entry.get("error_code") or "").strip()
        error_chip = (
            f"<span class='chip error'>{html.escape(entry_error_code)}</span>"
            if entry_error_code
            else ""
        )
        transcript_cards.append(
            "<article class='turn-card'>"
            f"<div class='turn-user'><div class='turn-head'><span class='chip'>user</span><span class='chip muted'>{entry_status}</span></div><p>{entry_title}</p></div>"
            f"<div class='turn-assistant'><div class='turn-head'><span class='chip'>assistant</span>{error_chip}</div><p>{entry_subtitle}</p><a class='trace-link' href='{html.escape(entry_href)}'>Open Trace</a></div>"
            "</article>"
        )
    transcript_html = (
        "<section class='transcript'>"
        "<div class='transcript-head'><h2>Conversation History</h2>"
        f"<p>{html.escape(str((active_session or {}).get('conversation_id') or (active_session or {}).get('session_id') or ''))}</p></div>"
        f"{''.join(transcript_cards) if transcript_cards else '<p class=\"empty\">No session selected.</p>'}"
        "</section>"
    )

    return (
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Trace Viewer</title><style>"
        "body{margin:0;background:#f3efe7;color:#1a2430;font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}"
        ".page{max-width:1320px;margin:0 auto;padding:28px 22px 48px}.hero{display:flex;justify-content:space-between;gap:20px;align-items:end;margin-bottom:20px}"
        ".hero h1{margin:0;font-size:34px}.hero p{margin:8px 0 0;color:#5d6975}.toolbar{display:flex;gap:12px;align-items:center;margin:18px 0 22px}.search{flex:1;background:#fff;border:1px solid #d6cfc2;border-radius:14px;padding:14px 16px;font-size:15px}"
        ".stats{font-size:13px;color:#5d6975}.layout{display:grid;grid-template-columns:360px 1fr;gap:18px;align-items:start}.grid{display:grid;gap:14px}"
        ".card{display:block;background:#fffdf9;border:1px solid #d6cfc2;border-radius:18px;padding:16px;box-shadow:0 10px 24px rgba(26,36,48,.06)}.card.active{border-color:#1b3b5b;box-shadow:0 0 0 2px rgba(27,59,91,.1),0 10px 24px rgba(26,36,48,.06)}"
        ".card:hover{transform:translateY(-1px);box-shadow:0 14px 28px rgba(26,36,48,.1)}.card-title{font-size:17px;font-weight:800;margin-bottom:10px;line-height:1.35}"
        ".card-main-link{text-decoration:none;color:inherit}.card-links{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}.mini-link{display:inline-flex;align-items:center;padding:6px 10px;border-radius:999px;background:#e6edf3;color:#1b3b5b;text-decoration:none;font-size:12px;font-weight:700}"
        ".card-meta{margin-bottom:10px}.card-subtitle{font-size:14px;color:#47515d;line-height:1.5;min-height:44px}"
        ".chip{display:inline-flex;align-items:center;padding:4px 10px;border-radius:999px;background:#e5ebf0;color:#1b3b5b;margin:0 6px 6px 0;font-size:12px;font-weight:700}.chip.muted{background:#ede6d8;color:#5d6975}.chip.error{background:#f3d9d9;color:#8f2525}"
        ".transcript{background:#fffdf9;border:1px solid #d6cfc2;border-radius:24px;padding:18px;box-shadow:0 10px 24px rgba(26,36,48,.06)}.transcript-head h2{margin:0;font-size:18px}.transcript-head p{margin:6px 0 0;color:#5d6975}.turn-card{display:grid;gap:10px;margin-top:14px}.turn-user,.turn-assistant{padding:14px 16px;border-radius:18px}.turn-user{background:#edf2f6}.turn-assistant{background:#f6efe2}.turn-head{display:flex;gap:8px;align-items:center;margin-bottom:8px}.turn-user p,.turn-assistant p{margin:0;line-height:1.6}.trace-link{display:inline-flex;align-items:center;margin-top:10px;padding:8px 12px;border-radius:999px;background:#1b3b5b;color:#fff;text-decoration:none;font-size:12px;font-weight:700}"
        "@media (max-width:720px){.hero{display:block}.toolbar{display:block}.search{width:100%}.layout{grid-template-columns:1fr}}"
        "</style></head><body><div class='page'>"
        "<section class='hero'><div><h1>Trace Viewer</h1><p>先看会话历史，再进入单条 turn 的 trace 细节。</p></div>"
        f"<div class='stats'>{session_count} sessions · {count} items</div></section>"
        "<section class='toolbar'><input id='search' class='search' placeholder='搜索 event_id / trace_id / 消息内容 / error_code'></section>"
        "<section class='layout'>"
        f"<section id='grid' class='grid'>{''.join(cards) if cards else '<p>No traces found.</p>'}</section>"
        f"{transcript_html}"
        "</section>"
        "<script>const input=document.getElementById('search');const cards=[...document.querySelectorAll('.card')];"
        "input.addEventListener('input',()=>{const q=input.value.trim().toLowerCase();for(const card of cards){card.style.display=!q||card.dataset.search.includes(q)?'block':'none';}});</script>"
        "</div></body></html>"
    )


def trace_serve_response(*, data_dir: str | Path, path: str) -> tuple[int, str, bytes]:
    parsed = urlparse(path)
    query = {k: v[-1] for k, v in parse_qs(parsed.query).items() if v}
    base = Path(data_dir)
    route = parsed.path or "/"

    if route in {"", "/"}:
        body = render_trace_catalog_html(build_trace_catalog(data_dir=base), selected_session_id=query.get("session_id"))
        return HTTPStatus.OK, "text/html; charset=utf-8", body.encode("utf-8")

    if route == "/api/catalog":
        body = json.dumps(build_trace_catalog(data_dir=base), ensure_ascii=False, sort_keys=True)
        return HTTPStatus.OK, "application/json; charset=utf-8", body.encode("utf-8")

    if route in {"/trace", "/api/trace"}:
        view = build_trace_view(
            data_dir=base,
            trace_id=query.get("trace_id"),
            event_id=query.get("event_id"),
            workspace_id=str(query.get("workspace_id") or "local"),
            turn_id=query.get("turn_id"),
        )
        pa_event = ((view.get("pa") or {}).get("event") or {})
        session_payload: dict[str, Any] = {}
        envelope = pa_event.get("envelope") if isinstance(pa_event, dict) else {}
        if isinstance(envelope, dict):
            conversation_id = str(envelope.get("conversation_id") or "").strip()
            workspace_id = str((view.get("requested") or {}).get("workspace_id") or "local")
            if conversation_id:
                catalog = build_trace_catalog(data_dir=base, limit=500)
                for session in catalog.get("sessions") or []:
                    if (
                        isinstance(session, dict)
                        and str(session.get("workspace_id") or "") == workspace_id
                        and str(session.get("conversation_id") or "") == conversation_id
                    ):
                        session_payload = session
                        break
        if session_payload:
            view = dict(view)
            view["session"] = session_payload
        if route == "/api/trace":
            body = json.dumps(view, ensure_ascii=False, sort_keys=True)
            status = HTTPStatus.OK if view.get("ok") is True else HTTPStatus.NOT_FOUND
            return status, "application/json; charset=utf-8", body.encode("utf-8")
        body = render_trace_view_html(view)
        status = HTTPStatus.OK if view.get("ok") is True else HTTPStatus.NOT_FOUND
        return status, "text/html; charset=utf-8", body.encode("utf-8")

    body = "<!doctype html><html><body><h1>404</h1><p>Not Found</p></body></html>"
    return HTTPStatus.NOT_FOUND, "text/html; charset=utf-8", body.encode("utf-8")


def run(argv: Optional[list[str]] = None) -> tuple[int, dict[str, Any]]:
    ap = argparse.ArgumentParser(prog="trace_view", add_help=True)
    ap.add_argument("--data-dir", default="data", help="Data dir containing traces/, evidence/, pa/ and idempotency/ (default: data)")
    ap.add_argument("--trace-id", help="Trace ID to inspect")
    ap.add_argument("--turn-id", help="Optional turn ID filter")
    ap.add_argument("--event-id", help="Optional PA event_id, e.g. tg_update_299891376")
    ap.add_argument("--workspace-id", default="local", help="Workspace ID for PA files (default: local)")
    args = ap.parse_args(argv)

    trace_id = str(args.trace_id or "").strip() or None
    event_id = str(args.event_id or "").strip() or None
    turn_id = str(args.turn_id or "").strip() or None
    workspace_id = str(args.workspace_id or "local").strip() or "local"
    if trace_id is None and event_id is None:
        out = {
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "error_code": "E_INPUT_SCHEMA",
            "message": "trace_id or event_id is required",
        }
        return 3, out

    out = build_trace_view(
        data_dir=Path(args.data_dir),
        trace_id=trace_id,
        event_id=event_id,
        workspace_id=workspace_id,
        turn_id=turn_id,
    )
    return (0 if out.get("ok") is True else 2), out


def main() -> None:
    try:
        code, out = run()
    except SystemExit:
        raise
    except Exception as e:
        code = 3
        out = {"schema_version": SCHEMA_VERSION, "ok": False, "error_code": "E_TOOL_ERROR", "message": str(e)}
    sys.stdout.write(json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    raise SystemExit(code)


if __name__ == "__main__":  # pragma: no cover
    main()
