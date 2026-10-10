from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentos_next.apps.assistant_loop import AssistantLoopRequest
from agentos_next.apps.assistant_runtime import run_assistant_runtime_async
from agentos_next.apps.canonical_task_ingress import build_canonical_task_ingress_request
from agentos_next.apps.channel_gateway import (
    ChannelGatewayConfig,
    ChannelGatewayService,
    ChannelInputError,
)
from agentos_next.apps.daemon_runner import (
    DaemonRunRequest,
    read_daemon_status,
    run_daemon_async,
    run_daemon_once_async,
)
from agentos_next.apps.pa_polling_service import PAPollingService, PAPollingServiceConfig
from agentos_next.apps.pa_webhook_server import PAWebhookService, PAWebhookServiceConfig
from agentos_next.apps.personal_assistant_demo import (
    PersonalAssistantDemoRequest,
    run_personal_assistant_demo,
)
from agentos_next.apps.scheduler_tick import SchedulerTickRequest, run_scheduler_tick_async
from agentos_next.apps.si1 import si1_observe, si1_propose, si1_validate
from agentos_next.apps.ui1 import (
    UI1RunOnceRequest,
    ui1_approve,
    ui1_list_approvals,
    ui1_reject,
    ui1_run_once,
)
from agentos_next.creator import CreatorError, build_creator_plan
from agentos_next.evals import compare_memory_effect_reports, run_memory_effect_eval
from agentos_next.kernel.dialog_state_machine import build_user_message_digest
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.skill_registry import FileSkillRegistry, SkillRegistryError
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import TraceContext, TraceEvent
from agentos_next.llm import is_remote_llm_backend
from agentos_next.pa.runtime_error_codes import PA_RUNTIME_ERROR_REPLAY_DENY
from agentos_next.release.pack import cmd_mvp_rc_pack, cmd_mvp_release_pack
from agentos_next.runtime.local_executor import LocalExecutor
from agentos_next.runtime.package_runner import PackageRunner, PackageRunRequest
from agentos_next.runtime.task_runner import SkillInvocation, TaskRunner, load_skill_contract
from agentos_next.tools.trace_view import (
    build_trace_view,
    render_trace_view_html,
    trace_serve_response,
)

_PA_POLLING_TRANSIENT_ERRORS = {
    "E_PA_POLLING_TRANSIENT_NETWORK",
    "E_PA_POLLING_FAILED",
}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"

def _derive_replayable_id(prefix: str, *, trace_id: str, index: int) -> str:
    """Derive a stable, replayable ID for a given session trace + 1-based index."""
    if index < 1:
        raise ValueError("index must be >= 1")
    seed = f"{prefix}:{trace_id}:{index}".encode("utf-8")
    # Fixed length so downstream tooling doesn't need to handle unbounded IDs.
    digest = hashlib.sha256(seed).hexdigest()[:16]
    return f"{prefix}_{index}_{digest}"


def _repo_root() -> Path:
    # src/agentos_next/cli.py -> repo root is 2 levels up (agentos-next/).
    # Keep deterministic so `python -m agentos_next.cli ...` works from any CWD.
    return Path(__file__).resolve().parents[2]


def _load_arguments(args: argparse.Namespace) -> dict:
    input_file = getattr(args, "input_file", None)
    if input_file:
        p = Path(input_file)
        return json.loads(p.read_text(encoding="utf-8"))
    input_text = getattr(args, "input", None)
    if input_text:
        return json.loads(input_text)
    arguments_file = getattr(args, "arguments_file", None)
    if arguments_file:
        p = Path(arguments_file)
        return json.loads(p.read_text(encoding="utf-8"))
    arguments_text = getattr(args, "arguments", None)
    if arguments_text:
        return json.loads(arguments_text)
    return {}


def cmd_mvp_run_skill(args: argparse.Namespace) -> int:
    contract, contract_path = load_skill_contract(args.contract)
    input_value = _load_arguments(args)
    if not isinstance(input_value, dict):
        print("arguments must be a JSON object", file=sys.stderr)
        return 2

    trace = TraceContext(
        trace_id=args.trace_id or _new_id("tr"),
        turn_id=args.turn_id or _new_id("turn"),
        span_id=args.span_id or _new_id("span"),
        parent_span_id=args.parent_span_id,
    )

    runner = TaskRunner.for_data_dir(args.data_dir)
    res = runner.run(
        SkillInvocation(
            contract=contract,
            contract_path=contract_path,
            input=input_value,
            workspace_id=args.workspace_id,
            trace=trace,
        )
    )

    # Print a stable JSON object for tooling.
    print(
        json.dumps(
            {
                "ok": res.ok,
                "output": res.output,
                "error": res.error,
                "trace_id": res.trace.trace_id,
                "turn_id": res.trace.turn_id,
                "span_id": res.trace.span_id,
                "evidence_refs": [er.ref for er in res.evidence_refs],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if res.ok else 1


def cmd_mvp_run_package(args: argparse.Namespace) -> int:
    input_value = _load_arguments(args)
    if not isinstance(input_value, dict):
        print("input must be a JSON object", file=sys.stderr)
        return 2

    trace = TraceContext(
        trace_id=args.trace_id or _new_id("tr"),
        turn_id=args.turn_id or _new_id("turn"),
        span_id=args.span_id or _new_id("span"),
        parent_span_id=args.parent_span_id,
    )

    runner = PackageRunner.for_data_dir(args.data_dir)
    req = PackageRunRequest(
        skill_dir=Path(args.skill_dir),
        input_obj=input_value,
        workspace_id=args.workspace_id,
        trace=trace,
        verify_asvp=bool(args.verify_asvp),
        public_keys_dir=Path(args.keys_dir) if args.keys_dir else None,
        backend=args.backend,
        remote_calls_armed=bool(args.remote_calls_armed),
        allow_network_egress=bool(args.allow_network_egress),
        approved_by_human=bool(args.approved_by_human),
        replay_mode=bool(args.replay_mode),
    )
    res = runner.run(req)

    print(
        json.dumps(
            {
                "ok": res.ok,
                "output": res.output,
                "error": res.error_code,
                "trace_id": res.trace.trace_id,
                "turn_id": res.trace.turn_id,
                "span_id": res.trace.span_id,
                "evidence_refs": [er.ref for er in res.evidence_refs],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if res.ok else 1


def cmd_mvp_trace_view(args: argparse.Namespace) -> int:
    out = build_trace_view(
        data_dir=str(args.data_dir),
        trace_id=(str(args.trace_id) if getattr(args, "trace_id", None) else None),
        event_id=(str(args.event_id) if getattr(args, "event_id", None) else None),
        workspace_id=str(getattr(args, "workspace_id", "local") or "local"),
        turn_id=(str(args.turn_id) if getattr(args, "turn_id", None) else None),
    )
    html_out = getattr(args, "html_out", None)
    if html_out is not None:
        resolved = out.get("resolved") or {}
        requested = out.get("requested") or {}
        default_name = str(resolved.get("trace_id") or requested.get("event_id") or "trace_view").strip() or "trace_view"
        target = Path(str(args.data_dir)) / "trace_views" / f"{default_name}.html" if str(html_out) == "auto" else Path(str(html_out))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_trace_view_html(out), encoding="utf-8")
        out = dict(out)
        out["html_report_path"] = str(target.resolve())
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0 if out.get("ok") is True else 2


def cmd_mvp_trace_serve(args: argparse.Namespace) -> int:
    if not _is_loopback_host(str(args.host)):
        print(json.dumps({"ok": False, "error_code": "E_INPUT_SCHEMA"}, ensure_ascii=False, sort_keys=True))
        return 2

    max_requests = int(args.max_requests) if args.max_requests is not None else None
    request_count = {"n": 0}
    data_dir = str(args.data_dir)

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def _write(self, status_code: int, content_type: str, body: bytes) -> None:
            self.send_response(int(status_code))
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            status_code, content_type, body = trace_serve_response(data_dir=data_dir, path=self.path)
            self._write(status_code, content_type, body)
            request_count["n"] += 1
            if max_requests is not None and request_count["n"] >= max_requests:
                threading.Thread(target=self.server.shutdown, daemon=True).start()

    server = HTTPServer((str(args.host), int(args.port)), _Handler)
    print(json.dumps({"ok": True, "url": f"http://{args.host}:{int(args.port)}/", "data_dir": data_dir}, ensure_ascii=False, sort_keys=True))
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


def cmd_mvp_assistant_demo(args: argparse.Namespace) -> int:
    # Demo is a submitter over the canonical assistant runtime, not a separate package runner path.
    trace = TraceContext(
        trace_id=args.trace_id or _new_id("tr"),
        turn_id=args.turn_id or _new_id("turn"),
        span_id=args.span_id or _new_id("span"),
        parent_span_id=args.parent_span_id,
    )

    req = PersonalAssistantDemoRequest(
        query=args.query,
        skill_dir=Path(args.skill_dir) if args.skill_dir else None,
        verify_asvp=bool(args.verify_asvp),
        public_keys_dir=Path(args.keys_dir) if args.keys_dir else None,
        workspace_id=args.workspace_id,
        data_dir=args.data_dir,
        trace=trace,
        backend=args.backend,
        intent_backend=(str(args.intent_backend) if getattr(args, "intent_backend", None) else None),
        intent_model=(str(args.intent_model) if getattr(args, "intent_model", None) else None),
        communicator_backend=(
            str(args.communicator_backend) if getattr(args, "communicator_backend", None) else None
        ),
        communicator_model=(str(args.communicator_model) if getattr(args, "communicator_model", None) else None),
        response_language=(str(args.response_language) if getattr(args, "response_language", None) else None),
        remote_calls_armed=bool(args.remote_calls_armed),
        allow_network_egress=bool(args.allow_network_egress),
        approved_by_human=bool(args.approved_by_human),
        replay_mode=bool(args.replay_mode),
        model_id_override=args.model_id,
    )

    res = run_personal_assistant_demo(req)
    output_obj = dict(res.final_output or {}) if isinstance(res.final_output, dict) else {}
    if not str(output_obj.get("reply") or "").strip():
        fallback_reply = str(
            output_obj.get("text")
            or output_obj.get("message")
            or output_obj.get("summary")
            or output_obj.get("result")
            or ""
        ).strip()
        if fallback_reply:
            output_obj["reply"] = fallback_reply

    print(
        json.dumps(
            {
                "ok": res.ok,
                "output": output_obj,
                "error": res.error_code,
                "trace_id": res.trace.trace_id,
                "turn_id": res.trace.turn_id,
                "span_id": res.trace.span_id,
                "evidence_refs": list(res.evidence_refs),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if res.ok else 1


def cmd_mvp_assistant_loop(args: argparse.Namespace) -> int:
    trace = TraceContext(
        trace_id=args.trace_id or _new_id("tr"),
        turn_id=args.turn_id or _new_id("turn"),
        span_id=args.span_id or _new_id("span"),
        parent_span_id=args.parent_span_id,
    )

    skill_dir = Path(args.assistant_skill_dir).resolve() if args.assistant_skill_dir else None
    keys_dir = Path(args.keys_dir).resolve() if args.keys_dir else None

    capabilities_set = set(_parse_csv_tags(getattr(args, "capabilities", None)))
    selected_backends = {
        str(args.backend or "").strip().lower(),
        str(getattr(args, "planner_backend", "") or "").strip().lower(),
        str(getattr(args, "intent_backend", "") or "").strip().lower(),
        str(getattr(args, "communicator_backend", "") or "").strip().lower(),
    }
    if bool(args.remote_calls_armed) or any(is_remote_llm_backend(name) for name in selected_backends if name):
        capabilities_set.add("llm_remote")
    if bool(args.allow_network_egress):
        capabilities_set.add("net_egress")

    req = AssistantLoopRequest(
        query=str(args.query),
        assistant_skill_dir=skill_dir,
        workspace_id=str(args.workspace_id),
        data_dir=str(args.data_dir),
        trace=trace,
        idempotency_key=str(args.idempotency_key) if args.idempotency_key else None,
        deadline_ms=int(args.deadline_ms),
        verify_asvp=bool(args.verify_asvp),
        public_keys_dir=keys_dir,
        backend=str(args.backend),
        planner=str(args.planner),
        planner_backend=str(args.planner_backend) if args.planner_backend else None,
        model=str(args.model) if args.model else None,
        intent_backend=str(args.intent_backend) if getattr(args, "intent_backend", None) else None,
        intent_model=str(args.intent_model) if getattr(args, "intent_model", None) else None,
        communicator_backend=(
            str(args.communicator_backend) if getattr(args, "communicator_backend", None) else None
        ),
        communicator_model=(
            str(args.communicator_model) if getattr(args, "communicator_model", None) else None
        ),
        response_language=(str(args.response_language) if getattr(args, "response_language", None) else None),
        remote_calls_armed=bool(args.remote_calls_armed),
        allow_network_egress=bool(args.allow_network_egress),
        approved_by_human=bool(args.approved_by_human),
        replay_mode=bool(args.replay_mode),
        capabilities=",".join(sorted(capabilities_set)),
        followup_at=str(args.followup_at) if args.followup_at else None,
    )

    ingress = build_canonical_task_ingress_request(
        req,
        submitter="cli.mvp.assistant-loop",
        consumer="cli.stdout.json",
        raw_input=str(args.query),
        metadata={"command": "mvp assistant-loop"},
    )
    res = asyncio.run(
        run_assistant_runtime_async(
            ingress,
            runtime_mode=str(args.runtime_mode),
            direct_fallback=bool(args.direct_fallback),
        )
    )
    print(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "ok": bool(res.ok),
                "error_code": res.error_code,
                "final_output": res.final_output,
                "followup_plan_ref": res.followup_plan_ref,
                "steps": res.steps,
                "trace_id": res.trace.trace_id,
                "turn_id": res.trace.turn_id,
                "span_id": res.trace.span_id,
                "evidence_refs": list(res.evidence_refs),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if res.ok else 1


def cmd_mvp_assistant_loop_stdio(args: argparse.Namespace) -> int:
    """Spike-AL3: stdin-driven assistant loop.

    Reads one query per line from stdin. Reuses a single trace_id for the session,
    and derives replayable turn_id/span_id per input line.
    Prints one stable JSON line per input message.
    """
    trace_id = args.trace_id or _new_id("tr")

    skill_dir = Path(args.assistant_skill_dir).resolve() if args.assistant_skill_dir else None
    keys_dir = Path(args.keys_dir).resolve() if args.keys_dir else None

    async def _run() -> int:
        ok_all = True
        turns = 0
        evidence = FileEvidenceStore(data_dir=args.data_dir)
        trace_log = FileTraceLogger(data_dir=args.data_dir)

        # Session-level dialog event.
        trace_log.emit(
            TraceEvent(
                schema_version="1.0.0",
                ctx=TraceContext(trace_id=trace_id, turn_id="turn_session", span_id="span_session"),
                event_type="DIALOG_EVENT",  # type: ignore[arg-type]
                ts=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                evidence_refs=(),
                data={"dialog_event_type": "DIALOG_OPENED", "dialog_id": trace_id, "workspace_id": str(args.workspace_id)},
            )
        )
        for raw in sys.stdin:
            if args.max_turns is not None and turns >= int(args.max_turns):
                break

            line = raw.strip("\n")
            if not line.strip():
                continue

            idx = turns + 1  # 1-based for stable derivation
            trace = TraceContext(
                trace_id=trace_id,
                turn_id=_derive_replayable_id("turn", trace_id=trace_id, index=idx),
                span_id=_derive_replayable_id("span", trace_id=trace_id, index=idx),
                parent_span_id=None,
            )

            # Record user message as evidence (tool_io) and a dialog event (digest in trace).
            msg_ref = evidence.add_json(
                {"schema_version": "1.0.0", "type": "dialog_user_message", "turn_index": idx, "message": line},
                kind="tool_io",
            )
            trace_log.emit(
                TraceEvent(
                    schema_version="1.0.0",
                    ctx=trace,
                    event_type="DIALOG_EVENT",  # type: ignore[arg-type]
                    ts=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    evidence_refs=(msg_ref,),
                    data={
                        "dialog_event_type": "USER_MESSAGE_RECEIVED",
                        "dialog_id": trace_id,
                        "turn_index": idx,
                        "input_digest": build_user_message_digest(message=line),
                    },
                )
            )
            trace_log.emit(
                TraceEvent(
                    schema_version="1.0.0",
                    ctx=trace,
                    event_type="DIALOG_EVENT",  # type: ignore[arg-type]
                    ts=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    evidence_refs=(),
                    data={"dialog_event_type": "TURN_STARTED", "dialog_id": trace_id, "turn_index": idx},
                )
            )

            capabilities_set = set(_parse_csv_tags(getattr(args, "capabilities", None)))
            selected_backends = {
                str(args.backend or "").strip().lower(),
                str(getattr(args, "planner_backend", "") or "").strip().lower(),
                str(getattr(args, "intent_backend", "") or "").strip().lower(),
                str(getattr(args, "communicator_backend", "") or "").strip().lower(),
            }
            if bool(args.remote_calls_armed) or any(is_remote_llm_backend(name) for name in selected_backends if name):
                capabilities_set.add("llm_remote")
            if bool(args.allow_network_egress):
                capabilities_set.add("net_egress")

            req = AssistantLoopRequest(
                query=line,
                assistant_skill_dir=skill_dir,
                workspace_id=str(args.workspace_id),
                data_dir=str(args.data_dir),
                trace=trace,
                idempotency_key=str(args.idempotency_key) if args.idempotency_key else None,
                deadline_ms=int(args.deadline_ms),
                verify_asvp=bool(args.verify_asvp),
                public_keys_dir=keys_dir,
                backend=str(args.backend),
                planner=str(args.planner),
                planner_backend=str(args.planner_backend) if args.planner_backend else None,
                model=str(args.model) if args.model else None,
                intent_backend=str(args.intent_backend) if getattr(args, "intent_backend", None) else None,
                intent_model=str(args.intent_model) if getattr(args, "intent_model", None) else None,
                communicator_backend=(
                    str(args.communicator_backend) if getattr(args, "communicator_backend", None) else None
                ),
                communicator_model=(
                    str(args.communicator_model) if getattr(args, "communicator_model", None) else None
                ),
                response_language=(str(args.response_language) if getattr(args, "response_language", None) else None),
                remote_calls_armed=bool(args.remote_calls_armed),
                allow_network_egress=bool(args.allow_network_egress),
                approved_by_human=bool(args.approved_by_human),
                replay_mode=bool(args.replay_mode),
                capabilities=",".join(sorted(capabilities_set)),
                followup_at=str(args.followup_at) if args.followup_at else None,
            )

            ingress = build_canonical_task_ingress_request(
                req,
                submitter="cli.stdin.assistant-loop-stdio",
                consumer="cli.stdout.jsonl",
                raw_input=line,
                metadata={"command": "mvp assistant-loop-stdio", "turn_index": idx},
            )
            res = await run_assistant_runtime_async(
                ingress,
                runtime_mode=str(args.runtime_mode),
                direct_fallback=bool(args.direct_fallback),
            )
            ok_all = ok_all and bool(res.ok)

            final_snapshot_ref = res.evidence_refs[-1] if res.evidence_refs else None
            trace_log.emit(
                TraceEvent(
                    schema_version="1.0.0",
                    ctx=trace,
                    event_type="DIALOG_EVENT",  # type: ignore[arg-type]
                    ts=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    evidence_refs=(),
                    data={
                        "dialog_event_type": "TURN_FINISHED",
                        "dialog_id": trace_id,
                        "turn_index": idx,
                        "ok": bool(res.ok),
                        "error_code": res.error_code,
                        "final_snapshot_ref": final_snapshot_ref,
                    },
                )
            )

            print(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "ok": bool(res.ok),
                        "error_code": res.error_code,
                        "final_output": res.final_output,
                        "followup_plan_ref": res.followup_plan_ref,
                        "steps": res.steps,
                        "trace_id": res.trace.trace_id,
                        "turn_id": res.trace.turn_id,
                        "span_id": res.trace.span_id,
                        "evidence_refs": list(res.evidence_refs),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                flush=True,
            )
            turns += 1

        return 0 if ok_all else 1

    return int(asyncio.run(_run()))


def cmd_mvp_exec(args: argparse.Namespace) -> int:
    arguments = _load_arguments(args)
    if not isinstance(arguments, dict):
        print("arguments must be a JSON object", file=sys.stderr)
        return 2

    trace = TraceContext(
        trace_id=args.trace_id or _new_id("tr"),
        turn_id=args.turn_id or _new_id("turn"),
        span_id=args.span_id or _new_id("span"),
        parent_span_id=args.parent_span_id,
    )

    preferred_target = getattr(args, "target", None) or "auto"

    req = ExecuteRequest(
        workspace_id=args.workspace_id,
        operator_ref=args.operator_ref,
        arguments=arguments,
        idempotency_key=args.idempotency_key or _new_id("idem"),
        deadline_ms=int(args.deadline_ms),
        trace=trace,
        policy_context={
            "verify_asvp": bool(args.verify_asvp),
            "public_keys_dir": args.keys_dir,
            "backend": args.backend,
            "model": args.model,  # Model ID override for routing
            "remote_calls_armed": bool(args.remote_calls_armed),
            "allow_network_egress": bool(args.allow_network_egress),
            "approved_by_human": bool(args.approved_by_human),
            "replay_mode": bool(args.replay_mode),
        },
        preferred_target=preferred_target,
        budget_slice=args.budget_slice,
    )

    # Orchestrator now handles routing to LocalExecutor or RemoteExecutor
    local_exec = LocalExecutor.for_data_dir(args.data_dir)
    orchestrator = Orchestrator.for_data_dir(args.data_dir, local_executor=local_exec)
    res = asyncio.run(orchestrator.execute(req))
    print(
        json.dumps(
            {
                "artifact_refs": list(res.artifact_refs),
                "error_code": res.error_code,
                "evidence_refs": [er.ref for er in res.evidence_refs],
                "status": res.status,
                "target": res.target,
                "timing": {"ended_at": res.timing.ended_at, "started_at": res.timing.started_at},
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if res.status == "accepted" else 1


def cmd_mvp_registry_add(args: argparse.Namespace) -> int:
    """Spike-REG1: local-only registry index add (content-addressed skill_ref)."""
    reg = FileSkillRegistry(data_dir=args.data_dir)
    try:
        deps = None
        if args.deps_json:
            obj = json.loads(str(args.deps_json))
            if not isinstance(obj, list) or not all(isinstance(x, str) for x in obj):
                raise ValueError("--deps-json must be a JSON array of strings")
            deps = list(obj)
        entry = reg.register(skill_dir=Path(args.skill_dir), deps=deps)
    except SkillRegistryError as e:
        print(json.dumps({"ok": False, "error_code": "E_EXECUTION_FAILED", "message": str(e)}, ensure_ascii=False, sort_keys=True))
        return 1
    except Exception as e:
        print(json.dumps({"ok": False, "error_code": "E_INPUT_SCHEMA", "message": str(e)}, ensure_ascii=False, sort_keys=True))
        return 2

    evidence = FileEvidenceStore(data_dir=args.data_dir)
    ev = evidence.add_json(
        {
            "schema_version": "1.0.0",
            "type": "registry_add",
            "registry_id": entry.registry_id,
            "skill_dir": entry.skill_dir,
            "manifest_sha256": entry.manifest_sha256,
            "signer_id": entry.signer_id,
            "name": entry.name,
            "version": entry.version,
            "deps": list(entry.deps),
        },
        kind="routing",
    )

    print(
        json.dumps(
            {
                "ok": True,
                "error_code": None,
                "registry_id": entry.registry_id,
                "skill_ref": f"registry://{entry.registry_id}",
                "skill_dir": entry.skill_dir,
                "manifest_sha256": entry.manifest_sha256,
                "signer_id": entry.signer_id,
                "name": entry.name,
                "version": entry.version,
                "deps": list(entry.deps),
                "evidence_refs": [ev.ref],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def cmd_mvp_registry_resolve(args: argparse.Namespace) -> int:
    """REG2: resolve registryq://name@constraint to registry://<registry_id> deterministically."""
    reg = FileSkillRegistry(data_dir=args.data_dir)
    evidence = FileEvidenceStore(data_dir=args.data_dir)

    try:
        rid = reg.resolve_query_ref(query_ref=str(args.ref))
        deps_map = reg.resolve_deps(root_registry_id=rid) if bool(args.with_deps) else {}
    except SkillRegistryError as e:
        ev = evidence.add_json(
            {"schema_version": "1.0.0", "type": "registry_resolve_error", "ref": str(args.ref), "message": str(e)},
            kind="error",
        )
        print(json.dumps({"ok": False, "error_code": "E_EXECUTION_FAILED", "evidence_refs": [ev.ref]}, ensure_ascii=False, sort_keys=True))
        return 1

    ev = evidence.add_json(
        {
            "schema_version": "1.0.0",
            "type": "registry_resolve",
            "ref": str(args.ref),
            "selected_registry_id": rid,
            "selected_skill_ref": f"registry://{rid}",
            "deps": deps_map,
        },
        kind="routing",
    )

    print(
        json.dumps(
            {
                "ok": True,
                "error_code": None,
                "ref": str(args.ref),
                "registry_id": rid,
                "skill_ref": f"registry://{rid}",
                "deps": deps_map,
                "evidence_refs": [ev.ref],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def cmd_mvp_scheduler_tick(args: argparse.Namespace) -> int:
    """Spike-SCHED1: fire due scheduled tasks (explicit tick runner)."""
    trace = TraceContext(
        trace_id=args.trace_id or _new_id("tr"),
        turn_id=args.turn_id or _new_id("turn"),
        span_id=args.span_id or _new_id("span"),
        parent_span_id=args.parent_span_id,
    )

    local_exec = LocalExecutor.for_data_dir(args.data_dir)
    orchestrator = Orchestrator.for_data_dir(args.data_dir, local_executor=local_exec)

    tick_req = SchedulerTickRequest(
        data_dir=str(args.data_dir),
        now=str(args.now) if args.now else None,
        replay_mode=bool(args.replay_mode),
        remote_calls_armed=bool(args.remote_calls_armed),
        allow_network_egress=bool(args.allow_network_egress),
        approved_by_human=bool(args.approved_by_human),
        max_fires=int(args.max_fires),
        trace=trace,
    )

    res = asyncio.run(run_scheduler_tick_async(tick_req, orchestrator=orchestrator))
    print(
        json.dumps(
            {
                "ok": bool(res.ok),
                "error_code": res.error_code,
                "now": str(args.now) if args.now else None,
                "fired": [
                    {
                        "task_id": ft.task_id,
                        "kind": ft.kind,
                        "fired_at": ft.fired_at,
                        "trace_id": ft.trace_id,
                        "execute_status": ft.execute_status,
                        "error_code": ft.error_code,
                        "target": ft.target,
                        "evidence_refs": list(ft.evidence_refs),
                        "next_run_at": ft.next_run_at,
                    }
                    for ft in res.fired
                ],
                "evidence_refs": list(res.evidence_refs),
                "trace_id": trace.trace_id,
                "turn_id": trace.turn_id,
                "span_id": trace.span_id,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if res.ok else 1


def _daemon_result_to_json(res: Any) -> dict[str, Any]:
    return {
        "ok": bool(res.ok),
        "error_code": res.error_code,
        "state": res.state,
        "last_tick_at": res.last_tick_at,
        "next_fire_at": res.next_fire_at,
        "consecutive_failures": int(res.consecutive_failures),
        "cumulative_failures": int(res.cumulative_failures),
        "pid": int(res.pid),
        "uptime_ms": int(res.uptime_ms),
        "evidence_refs": list(res.evidence_refs),
    }


def cmd_mvp_daemon_status(args: argparse.Namespace) -> int:
    res = read_daemon_status(data_dir=str(args.data_dir))
    print(json.dumps(_daemon_result_to_json(res), ensure_ascii=False, sort_keys=True))
    return 0


def cmd_mvp_daemon_run_once(args: argparse.Namespace) -> int:
    req = DaemonRunRequest(
        data_dir=str(args.data_dir),
        tick_interval_ms=int(args.tick_interval_ms),
        max_fires_per_tick=int(args.max_fires),
        replay_mode=bool(args.replay_mode),
        remote_calls_armed=bool(args.remote_calls_armed),
        allow_network_egress=bool(args.allow_network_egress),
        approved_by_human=bool(args.approved_by_human),
        strict_mode=bool(args.strict_mode),
        now=(str(args.now) if args.now else None),
        max_loops=1,
    )
    try:
        res = asyncio.run(run_daemon_once_async(req))
    except Exception as e:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_code": "E_EXECUTION_FAILED",
                    "state": "blocked",
                    "last_tick_at": None,
                    "next_fire_at": None,
                    "consecutive_failures": 0,
                    "cumulative_failures": 0,
                    "pid": 0,
                    "uptime_ms": 0,
                    "evidence_refs": [],
                    "message": str(e),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(_daemon_result_to_json(res), ensure_ascii=False, sort_keys=True))
    return 0 if res.ok else 1


def cmd_mvp_daemon_run(args: argparse.Namespace) -> int:
    req = DaemonRunRequest(
        data_dir=str(args.data_dir),
        tick_interval_ms=int(args.tick_interval_ms),
        max_fires_per_tick=int(args.max_fires),
        replay_mode=bool(args.replay_mode),
        remote_calls_armed=bool(args.remote_calls_armed),
        allow_network_egress=bool(args.allow_network_egress),
        approved_by_human=bool(args.approved_by_human),
        strict_mode=bool(args.strict_mode),
        now=(str(args.now) if args.now else None),
        max_loops=(int(args.max_loops) if args.max_loops is not None else None),
    )
    try:
        res = asyncio.run(run_daemon_async(req))
    except Exception as e:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_code": "E_EXECUTION_FAILED",
                    "state": "blocked",
                    "last_tick_at": None,
                    "next_fire_at": None,
                    "consecutive_failures": 0,
                    "cumulative_failures": 0,
                    "pid": 0,
                    "uptime_ms": 0,
                    "evidence_refs": [],
                    "message": str(e),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(_daemon_result_to_json(res), ensure_ascii=False, sort_keys=True))
    return 0 if res.ok else 1


def cmd_mvp_si1_observe(args: argparse.Namespace) -> int:
    res = si1_observe(data_dir=args.data_dir, run_id=str(args.run_id) if args.run_id else None, replay_mode=bool(args.replay_mode))
    print(json.dumps(res, ensure_ascii=False, sort_keys=True))
    return 0 if res.get("ok") is True else 1


def cmd_mvp_si1_propose(args: argparse.Namespace) -> int:
    res = si1_propose(data_dir=args.data_dir, run_id=str(args.run_id), replay_mode=bool(args.replay_mode))
    print(json.dumps(res, ensure_ascii=False, sort_keys=True))
    return 0 if res.get("ok") is True else 1


def cmd_mvp_si1_validate(args: argparse.Namespace) -> int:
    res = si1_validate(data_dir=args.data_dir, run_id=str(args.run_id), replay_mode=bool(args.replay_mode))
    print(json.dumps(res, ensure_ascii=False, sort_keys=True))
    return 0 if res.get("ok") is True else 1


def _channel_error_output(
    *,
    error_code: str,
    trace_id: str | None = None,
    turn_id: str | None = None,
    span_id: str | None = None,
    status: str = "rejected",
) -> dict[str, Any]:
    return {
        "ok": False,
        "status": status,
        "error_code": error_code,
        "trace_id": str(trace_id or ""),
        "turn_id": str(turn_id or ""),
        "span_id": str(span_id or ""),
        "evidence_refs": [],
        "artifact_refs": [],
    }


def _parse_channel_line(raw: str, *, json_lines: bool) -> dict[str, Any] | None:
    line = raw.strip("\n")
    if not line.strip():
        return None

    if json_lines:
        obj = json.loads(line)
        if not isinstance(obj, dict):
            raise ValueError("channel json line must be a JSON object")
        return obj

    return {"message": line}


def cmd_mvp_channel_stdio(args: argparse.Namespace) -> int:
    """Spike-OC1: minimal stdin channel adapter.

    Reads messages from stdin and converts them to ExecuteRequest(s) routed through Orchestrator/LocalExecutor.
    Prints one stable JSON line per input message.
    """
    root = _repo_root()

    if args.operator_ref is None:
        args.operator_ref = str(root / "examples" / "skills" / "personal_assistant_brief")
        if args.keys_dir is None:
            args.keys_dir = str(root / "examples" / "keys")

    if bool(args.verify_asvp) and not args.keys_dir:
        print("--keys-dir is required when --verify-asvp is enabled", file=sys.stderr)
        return 2

    trace_id = args.trace_id or _new_id("tr")
    preferred_target = getattr(args, "target", None) or "auto"
    service = ChannelGatewayService(
        ChannelGatewayConfig(
            data_dir=str(args.data_dir),
            operator_ref=str(args.operator_ref),
            keys_dir=(str(args.keys_dir) if args.keys_dir else None),
            verify_asvp=bool(args.verify_asvp),
            target=str(preferred_target),
            backend=str(args.backend),
            model=(str(getattr(args, "model")) if getattr(args, "model", None) else None),
            remote_calls_armed=bool(args.remote_calls_armed),
            allow_network_egress=bool(args.allow_network_egress),
            approved_by_human=bool(args.approved_by_human),
            replay_mode=bool(args.replay_mode),
            workspace_id=str(args.workspace_id),
            deadline_ms=int(args.deadline_ms),
        )
    )

    async def _run() -> int:
        ok_all = True
        turns = 0
        for raw in sys.stdin:
            if args.max_turns is not None and turns >= int(args.max_turns):
                break

            try:
                payload = _parse_channel_line(raw, json_lines=bool(args.json_lines))
            except Exception:
                print(
                    json.dumps(
                        _channel_error_output(
                            error_code="E_BAD_CHANNEL_INPUT",
                            trace_id=trace_id,
                            status="rejected",
                        ),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    flush=True,
                )
                ok_all = False
                continue

            if payload is None:
                continue

            try:
                out = await service.execute(payload, trace_id_default=trace_id)
            except ChannelInputError:
                out = _channel_error_output(error_code="E_BAD_CHANNEL_INPUT", trace_id=trace_id, status="rejected")
            except Exception:
                out = _channel_error_output(error_code="E_EXECUTION_FAILED", trace_id=trace_id, status="failed")

            ok = bool(out.get("ok") is True)
            ok_all = ok_all and ok

            print(json.dumps(out, ensure_ascii=False, sort_keys=True), flush=True)
            turns += 1

        return 0 if ok_all else 1

    return int(asyncio.run(_run()))


def _is_loopback_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def _parse_csv_tags(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    try:
        raw = str(value)
    except Exception:
        return ()
    out: list[str] = []
    for part in raw.split(","):
        token = part.strip()
        if token and token not in out:
            out.append(token)
    return tuple(out)


def _channel_http_process_body(*, raw_body: bytes, service: ChannelGatewayService) -> tuple[int, dict[str, Any]]:
    try:
        obj = json.loads(raw_body.decode("utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("request body must be object")
    except Exception:
        return 400, _channel_error_output(error_code="E_BAD_CHANNEL_INPUT", status="rejected")

    try:
        return 200, service.execute_sync(obj, trace_id_default=None)
    except ChannelInputError:
        return 400, _channel_error_output(error_code="E_BAD_CHANNEL_INPUT", status="rejected")
    except Exception:
        return 500, _channel_error_output(error_code="E_EXECUTION_FAILED", status="failed")


def cmd_mvp_channel_http(args: argparse.Namespace) -> int:
    root = _repo_root()

    if args.operator_ref is None:
        args.operator_ref = str(root / "examples" / "skills" / "personal_assistant_brief")
        if args.keys_dir is None:
            args.keys_dir = str(root / "examples" / "keys")

    if bool(args.verify_asvp) and not args.keys_dir:
        print("--keys-dir is required when --verify-asvp is enabled", file=sys.stderr)
        return 2

    if not _is_loopback_host(str(args.host)):
        print(
            json.dumps(
                _channel_error_output(error_code="E_INPUT_SCHEMA", status="rejected"),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    preferred_target = getattr(args, "target", None) or "auto"
    service = ChannelGatewayService(
        ChannelGatewayConfig(
            data_dir=str(args.data_dir),
            operator_ref=str(args.operator_ref),
            keys_dir=(str(args.keys_dir) if args.keys_dir else None),
            verify_asvp=bool(args.verify_asvp),
            target=str(preferred_target),
            backend=str(args.backend),
            model=(str(getattr(args, "model")) if getattr(args, "model", None) else None),
            remote_calls_armed=bool(args.remote_calls_armed),
            allow_network_egress=bool(args.allow_network_egress),
            approved_by_human=bool(args.approved_by_human),
            replay_mode=bool(args.replay_mode),
            workspace_id=str(args.workspace_id),
            deadline_ms=int(args.deadline_ms),
        )
    )

    max_requests = int(args.max_requests) if args.max_requests is not None else None
    request_count = {"n": 0}

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def _write_json(self, status_code: int, body_obj: dict[str, Any]) -> None:
            body = json.dumps(body_obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            handled = False
            if self.path != "/v1/channel/messages":
                self._write_json(404, _channel_error_output(error_code="E_BAD_CHANNEL_INPUT", status="rejected"))
                handled = True
            else:
                raw_len = self.headers.get("Content-Length")
                n = int(raw_len) if raw_len is not None else 0
                raw = self.rfile.read(max(0, n))
                code, out = _channel_http_process_body(raw_body=raw, service=service)
                self._write_json(code, out)
                handled = True

            if handled:
                request_count["n"] += 1
                if max_requests is not None and request_count["n"] >= max_requests:
                    threading.Thread(target=self.server.shutdown, daemon=True).start()

    server = HTTPServer((str(args.host), int(args.port)), _Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


def cmd_mvp_pa_demo(args: argparse.Namespace) -> int:
    """THREAD-040: minimal visible PA roundtrip (Telegram webhook -> canonical runtime -> outbox -> reply stub)."""
    root = _repo_root()

    # Load webhook payload (default to repo sample fixture).
    payload_str: str
    if getattr(args, "payload", None):
        payload_str = str(args.payload)
    else:
        payload_file = getattr(args, "payload_file", None)
        if payload_file is None:
            payload_file = str(root / "examples" / "fixtures" / "telegram_webhook_sample.json")
        try:
            payload_str = Path(str(payload_file)).read_text(encoding="utf-8")
        except Exception:
            print(json.dumps({"ok": False, "error_code": "E_PA_DEMO_INPUT_INVALID"}, ensure_ascii=False, sort_keys=True))
            return 2

    expected = str(getattr(args, "expected_secret_token", "") or "").strip()
    if not expected:
        print(json.dumps({"ok": False, "error_code": "E_PA_DEMO_INPUT_INVALID"}, ensure_ascii=False, sort_keys=True))
        return 2

    provided = getattr(args, "secret_token", None)
    provided_token = str(provided).strip() if provided is not None else expected

    operator_ref = getattr(args, "operator_ref", None)
    if not operator_ref:
        operator_ref = str(root / "examples" / "skills" / "personal_assistant_brief")
    keys_dir = getattr(args, "keys_dir", None)
    if keys_dir is None:
        keys_dir = str(root / "examples" / "keys")

    cfg = PAWebhookServiceConfig(
        data_dir=str(args.data_dir),
        workspace_id=str(args.workspace_id),
        expected_secret_token=expected,
        budget_slice_remote_llm_calls=(
            int(getattr(args, "budget_slice_remote_llm_calls"))
            if getattr(args, "budget_slice_remote_llm_calls", None) is not None
            else None
        ),
        replay_mode=bool(getattr(args, "replay_mode", False)),
        bot_token=str(getattr(args, "bot_token", "stub-token")),
        operator_ref=str(operator_ref),
        message_input_key=str(getattr(args, "message_input_key", "request") or "request"),
        verify_asvp=bool(getattr(args, "verify_asvp", True)),
        keys_dir=(str(keys_dir) if keys_dir else None),
        backend=str(getattr(args, "backend", "local_mock") or "local_mock"),
        model=(str(getattr(args, "model")) if getattr(args, "model", None) else None),
        remote_calls_armed=bool(getattr(args, "remote_calls_armed", False)),
        allow_network_egress=bool(getattr(args, "allow_network_egress", False)),
        approved_by_human=bool(getattr(args, "approved_by_human", False)),
        target=str(getattr(args, "target", "local") or "local"),
        deadline_ms=int(getattr(args, "deadline_ms", 60000)),
        memory_context_enabled=bool(getattr(args, "memory_context_enabled", False)),
        memory_context_retrieval_limit=int(getattr(args, "memory_context_retrieval_limit", 8)),
        memory_context_include_stale=bool(getattr(args, "memory_context_include_stale", False)),
        memory_context_continuity_event_limit=int(
            getattr(args, "memory_context_continuity_event_limit", 50)
        ),
        memory_context_audit_mode=bool(getattr(args, "memory_context_audit_mode", False)),
    )
    service = PAWebhookService(cfg)

    try:
        http_code, runtime_body = service.handle_webhook_request(
            raw_body=payload_str.encode("utf-8"),
            secret_token=provided_token,
        )
    except Exception:
        print(json.dumps({"ok": False, "error_code": "E_PA_DEMO_FAILED"}, ensure_ascii=False, sort_keys=True))
        return 1

    out = dict(runtime_body or {}) if isinstance(runtime_body, dict) else {"ok": False, "error_code": "E_PA_DEMO_FAILED"}
    out["http_status"] = int(http_code)
    if bool(getattr(args, "replay_mode", False)) and not str(out.get("error_code") or "").strip():
        out["error_code"] = PA_RUNTIME_ERROR_REPLAY_DENY
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0 if out["ok"] else 1


def cmd_mvp_pa_webhook_server(args: argparse.Namespace) -> int:
    root = _repo_root()

    if not _is_loopback_host(str(args.host)):
        print(
            json.dumps(
                {"ok": False, "error_code": "E_INPUT_SCHEMA"},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    if getattr(args, "operator_ref", None) is None:
        args.operator_ref = str(root / "examples" / "skills" / "personal_assistant_brief")
        if args.keys_dir is None:
            args.keys_dir = str(root / "examples" / "keys")

    if bool(args.verify_asvp) and not args.keys_dir:
        print(json.dumps({"ok": False, "error_code": "E_INPUT_SCHEMA"}, ensure_ascii=False, sort_keys=True))
        return 2

    cfg = PAWebhookServiceConfig(
        data_dir=str(args.data_dir),
        workspace_id=str(args.workspace_id),
        routing_file=(str(args.routing_file) if getattr(args, "routing_file", None) else None),
        expected_secret_token=str(args.expected_secret_token),
        budget_slice_remote_llm_calls=getattr(args, "budget_slice_remote_llm_calls", None),
        replay_mode=bool(args.replay_mode),
        bot_token=str(args.bot_token),
        operator_ref=str(args.operator_ref),
        message_input_key=str(getattr(args, "message_input_key", "request") or "request"),
        verify_asvp=bool(args.verify_asvp),
        keys_dir=(str(args.keys_dir) if args.keys_dir else None),
        backend=str(args.backend),
        model=(str(args.model) if getattr(args, "model", None) else None),
        remote_calls_armed=bool(args.remote_calls_armed),
        allow_network_egress=bool(args.allow_network_egress),
        approved_by_human=bool(args.approved_by_human),
        target=str(args.target),
        deadline_ms=int(args.deadline_ms),
        memory_context_enabled=bool(getattr(args, "memory_context_enabled", False)),
        memory_context_retrieval_limit=int(getattr(args, "memory_context_retrieval_limit", 8)),
        memory_context_include_stale=bool(getattr(args, "memory_context_include_stale", False)),
        memory_context_continuity_event_limit=int(
            getattr(args, "memory_context_continuity_event_limit", 50)
        ),
        memory_context_audit_mode=bool(getattr(args, "memory_context_audit_mode", False)),
    )
    try:
        service = PAWebhookService(cfg)
    except (OSError, json.JSONDecodeError, ValueError):
        print(json.dumps({"ok": False, "error_code": "E_INPUT_SCHEMA"}, ensure_ascii=False, sort_keys=True))
        return 2

    max_requests = int(args.max_requests) if args.max_requests is not None else None
    request_count = {"n": 0}
    webhook_path = str(args.path)

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def _write_json(self, status_code: int, body_obj: dict[str, Any]) -> None:
            body = json.dumps(body_obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path != webhook_path:
                self._write_json(404, {"ok": False, "error_code": "E_BAD_CHANNEL_INPUT"})
            else:
                raw_len = self.headers.get("Content-Length")
                n = int(raw_len) if raw_len is not None else 0
                raw = self.rfile.read(max(0, n))
                secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token")
                code, out = service.handle_webhook_request(raw_body=raw, secret_token=secret)
                self._write_json(code, out)

            request_count["n"] += 1
            if max_requests is not None and request_count["n"] >= max_requests:
                threading.Thread(target=self.server.shutdown, daemon=True).start()

    server = HTTPServer((str(args.host), int(args.port)), _Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


def cmd_mvp_pa_polling(args: argparse.Namespace) -> int:
    root = _repo_root()

    if not str(getattr(args, "bot_token", "") or "").strip():
        print(json.dumps({"ok": False, "error_code": "E_INPUT_SCHEMA"}, ensure_ascii=False, sort_keys=True))
        return 2

    if getattr(args, "operator_ref", None) is None:
        args.operator_ref = str(root / "examples" / "skills" / "personal_assistant_brief")
        if args.keys_dir is None:
            args.keys_dir = str(root / "examples" / "keys")

    if bool(args.verify_asvp) and not args.keys_dir:
        print(json.dumps({"ok": False, "error_code": "E_INPUT_SCHEMA"}, ensure_ascii=False, sort_keys=True))
        return 2

    capabilities = set(_parse_csv_tags(getattr(args, "capabilities", None)))
    selected_backends = {
        str(args.backend or "").strip().lower(),
        str(getattr(args, "intent_backend", "") or "").strip().lower(),
        str(getattr(args, "communicator_backend", "") or "").strip().lower(),
    }
    if bool(args.remote_calls_armed) or any(is_remote_llm_backend(name) for name in selected_backends if name):
        capabilities.add("llm_remote")
    if bool(args.allow_network_egress):
        capabilities.add("net_egress")
    if getattr(args, "memory_context_enabled", False):
        capabilities.update(["memory_write", "memory_search", "memory_compact", "memory_delete"])

    cfg = PAPollingServiceConfig(
        data_dir=str(args.data_dir),
        workspace_id=str(args.workspace_id),
        routing_file=(str(args.routing_file) if getattr(args, "routing_file", None) else None),
        budget_slice_remote_llm_calls=getattr(args, "budget_slice_remote_llm_calls", None),
        replay_mode=bool(args.replay_mode),
        bot_token=str(args.bot_token),
        operator_ref=str(args.operator_ref),
        message_input_key=str(getattr(args, "message_input_key", "request") or "request"),
        verify_asvp=bool(args.verify_asvp),
        keys_dir=(str(args.keys_dir) if args.keys_dir else None),
        backend=str(args.backend),
        model=(str(args.model) if getattr(args, "model", None) else None),
        intent_backend=(str(args.intent_backend) if getattr(args, "intent_backend", None) else None),
        intent_model=(str(args.intent_model) if getattr(args, "intent_model", None) else None),
        communicator_backend=(
            str(args.communicator_backend) if getattr(args, "communicator_backend", None) else None
        ),
        communicator_model=(
            str(args.communicator_model) if getattr(args, "communicator_model", None) else None
        ),
        response_language=(str(args.response_language) if getattr(args, "response_language", None) else None),
        remote_calls_armed=bool(args.remote_calls_armed),
        allow_network_egress=bool(args.allow_network_egress),
        approved_by_human=bool(args.approved_by_human),
        target=str(args.target),
        deadline_ms=int(args.deadline_ms),
        capabilities=tuple(sorted(capabilities)),
        memory_context_enabled=bool(getattr(args, "memory_context_enabled", False)),
        memory_context_retrieval_limit=int(getattr(args, "memory_context_retrieval_limit", 8)),
        memory_context_include_stale=bool(getattr(args, "memory_context_include_stale", False)),
        memory_context_continuity_event_limit=int(
            getattr(args, "memory_context_continuity_event_limit", 50)
        ),
        memory_context_audit_mode=bool(getattr(args, "memory_context_audit_mode", False)),
        timeout_seconds=int(getattr(args, "timeout_seconds", 20)),
        limit=int(getattr(args, "limit", 20)),
        scheduler_auto_tick_enabled=bool(getattr(args, "scheduler_auto_tick", True)),
        scheduler_tick_max_fires=int(getattr(args, "scheduler_tick_max_fires", 20)),
    )

    try:
        service = PAPollingService(cfg)
    except (OSError, json.JSONDecodeError, ValueError):
        print(json.dumps({"ok": False, "error_code": "E_INPUT_SCHEMA"}, ensure_ascii=False, sort_keys=True))
        return 2

    max_cycles_raw = int(getattr(args, "max_cycles", 1))
    if max_cycles_raw < 0:
        print(json.dumps({"ok": False, "error_code": "E_INPUT_SCHEMA"}, ensure_ascii=False, sort_keys=True))
        return 2
    infinite = max_cycles_raw == 0
    max_cycles = max_cycles_raw if max_cycles_raw > 0 else 0
    offset = int(args.offset) if getattr(args, "offset", None) is not None else None
    total_processed = 0
    total_dedup = 0
    total_ignored_non_text = 0
    total_reply_sent = 0
    total_rejected = 0
    total_scheduler_fired = 0
    total_scheduler_errors = 0
    last_error: str | None = None
    last_error_detail: str | None = None
    consecutive_polling_errors = 0
    cycles_run = 0
    interrupted = False

    print(f"Starting PA polling service (backend: {cfg.backend})...")
    print(f"Max cycles: {'infinite' if infinite else max_cycles_raw}")
    capability_snapshot_fn = getattr(service, "capability_self_check_snapshot", None)
    capability_snapshot = capability_snapshot_fn() if callable(capability_snapshot_fn) else {}
    for line in list(capability_snapshot.get("summary_lines") or []):
        text = str(line or "").strip()
        if text:
            print(f"[PA] Capability self-check: {text}")
    if getattr(args, "offset", None) is not None:
        print(f"Starting from explicit offset: {int(args.offset)}")
    else:
        resume_fn = getattr(service, "resume_offset", None)
        resume_offset = resume_fn() if callable(resume_fn) else None
        if resume_offset is not None:
            print(f"Resuming from persisted offset: {resume_offset}")
    print("Waiting for Telegram updates...")

    try:
        while True:
            if (not infinite) and cycles_run >= max_cycles:
                break
            out = service.run_once(offset=offset)
            total_processed += int(out.get("processed") or 0)
            total_dedup += int(out.get("dedup") or 0)
            total_ignored_non_text += int(out.get("ignored_non_text") or 0)
            total_reply_sent += int(out.get("reply_sent") or 0)
            total_rejected += int(out.get("rejected") or 0)
            total_scheduler_fired += int(out.get("scheduler_fired") or 0)
            total_scheduler_errors += int(out.get("scheduler_errors") or 0)
            if out.get("error_code"):
                consecutive_polling_errors += 1
                last_error = str(out.get("error_code"))
                detail = str(out.get("error_detail") or "").strip()
                last_error_detail = detail or None
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "error_code": last_error,
                            "error_detail": last_error_detail,
                            "next_offset": out.get("next_offset"),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                if str(last_error) in _PA_POLLING_TRANSIENT_ERRORS:
                    backoff_seconds = min(8.0, 0.5 * (2 ** max(0, consecutive_polling_errors - 1)))
                    time.sleep(backoff_seconds)
            else:
                consecutive_polling_errors = 0
            next_offset = out.get("next_offset")
            offset = int(next_offset) if next_offset is not None else offset
            cycles_run += 1
    except KeyboardInterrupt:
        interrupted = True

    result = {
        "ok": last_error is None,
        "error_code": last_error,
        "processed": total_processed,
        "dedup": total_dedup,
        "ignored_non_text": total_ignored_non_text,
        "reply_sent": total_reply_sent,
        "rejected": total_rejected,
        "scheduler_fired": total_scheduler_fired,
        "scheduler_errors": total_scheduler_errors,
        "error_detail": last_error_detail,
        "next_offset": offset,
        "max_cycles": max_cycles_raw,
        "cycles_run": cycles_run,
        "infinite_mode": infinite,
        "interrupted": interrupted,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


def cmd_mvp_pa_login_openai(args: argparse.Namespace) -> int:
    import urllib.parse

    from agentos_next.llm.openai_codex_oauth import OpenAICodexOAuthProvider

    p = OpenAICodexOAuthProvider(
        remote_calls_armed=True,
        allow_network_egress=True,
        token_path=args.token_path,
    )

    sess = p.create_login_session(
        client_id=args.client_id,
        redirect_uri=args.redirect_uri,
    )

    print("=" * 60)
    print(" OpenAI Codex OAuth Login ")
    print("=" * 60)
    print("Please open the following URL in your browser and log in:")
    print()
    print(sess.authorize_url)
    print()
    print("-" * 60)
    print("After logging in, you will be redirected to a callback URL.")
    print("Please copy the FULL URL from your browser's address bar and paste it here.")
    print("(It should contain 'code=' and 'state=')")
    print("-" * 60)

    try:
        callback_url = input("Callback URL: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nLogin cancelled.")
        return 1

    if not callback_url:
        print("Error: No URL provided.")
        return 1

    try:
        parsed = urllib.parse.urlparse(callback_url)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]

        if not code or not state:
            print("Error: Could not find 'code' or 'state' in URL.")
            return 1

        if state != sess.state:
            print("Error: State mismatch (CSRF protection).")
            return 1

        print("Exchanging code for token...")
        p.exchange_code_for_token(
            code=code,
            code_verifier=sess.code_verifier,
            client_id=args.client_id,
            redirect_uri=args.redirect_uri,
        )
        print(f"Success! Token saved to: {p.token_path}")
        return 0
    except Exception as e:
        print(f"Error during login: {e}")
        return 1


def cmd_mvp_eval_memory(args: argparse.Namespace) -> int:
    try:
        strategy = str(args.strategy).upper()
        if strategy not in {"A", "B", "C"}:
            raise ValueError("strategy must be one of: A|B|C")
        report = run_memory_effect_eval(
            dataset_path=str(args.dataset),
            strategy=strategy,
            out_path=(str(args.out) if args.out else None),
            seed=int(args.seed),
        )
    except Exception as e:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_code": "E_MEMORY_EVAL_INVALID",
                    "error": str(e),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1

    report_path = str(Path(args.out).resolve()) if args.out else None
    print(
        json.dumps(
            {
                "ok": True,
                "error_code": None,
                "report": report,
                "report_path": report_path,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def cmd_mvp_eval_memory_compare(args: argparse.Namespace) -> int:
    try:
        baseline_strategy = str(args.baseline_strategy).upper()
        if baseline_strategy not in {"A", "B", "C"}:
            raise ValueError("baseline_strategy must be A|B|C")
        comparison = compare_memory_effect_reports(
            report_a_path=str(args.report_a),
            report_b_path=str(args.report_b),
            report_c_path=str(args.report_c),
            baseline_strategy=baseline_strategy,
            guard_epsilon=float(args.guard_epsilon),
            out_path=(str(args.out) if args.out else None),
        )
    except Exception as e:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_code": "E_MEMORY_EVAL_COMPARE_INVALID",
                    "error": str(e),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1

    comparison_path = str(Path(args.out).resolve()) if args.out else None
    print(
        json.dumps(
            {
                "ok": True,
                "error_code": None,
                "comparison": comparison,
                "comparison_path": comparison_path,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def cmd_mvp_creator_plan(args: argparse.Namespace) -> int:
    try:
        plan = build_creator_plan(
            registry_root=args.registry_root,
            intent=args.intent,
            workspace_id=args.workspace_id,
            deadline_ms=int(args.deadline_ms),
            max_steps=int(args.max_steps),
            model_id_override=args.model,
        )
    except CreatorError as e:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_code": e.code,
                    "error": str(e),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1

    plan_path = None
    if args.plan_out:
        out = Path(args.plan_out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        plan_path = str(out)

    print(
        json.dumps(
            {
                "ok": True,
                "error_code": None,
                "plan": plan,
                "plan_path": plan_path,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def cmd_mvp_ui_run_once(args: argparse.Namespace) -> int:
    msg = str(args.message or "").strip()
    if not msg:
        print(json.dumps({"ok": False, "error_code": "E_INPUT_SCHEMA", "message": "missing --message"}, ensure_ascii=False, sort_keys=True))
        return 2

    req = UI1RunOnceRequest(
        message=msg,
        operator_ref=str(args.operator_ref),
        workspace_id=str(args.workspace_id),
        data_dir=str(args.data_dir),
        keys_dir=str(args.keys_dir) if args.keys_dir else None,
        verify_asvp=bool(args.verify_asvp),
        backend=str(args.backend),
        model=str(args.model) if args.model else None,
        preferred_target=str(args.target or "auto"),
        deadline_ms=int(args.deadline_ms),
        remote_calls_armed=bool(args.remote_calls_armed),
        allow_network_egress=bool(args.allow_network_egress),
        approved_by_human=bool(args.approved_by_human),
        replay_mode=bool(args.replay_mode),
        trace_id=str(args.trace_id) if args.trace_id else None,
        turn_id=str(args.turn_id) if args.turn_id else None,
        span_id=str(args.span_id) if args.span_id else None,
        parent_span_id=str(args.parent_span_id) if args.parent_span_id else None,
        idempotency_key=str(args.idempotency_key) if args.idempotency_key else None,
    )
    res = ui1_run_once(req)
    print(json.dumps(res.to_json(), ensure_ascii=False, sort_keys=True))
    return 0 if res.ok else 1


def cmd_mvp_ui_approvals_list(args: argparse.Namespace) -> int:
    out = ui1_list_approvals(data_dir=str(args.data_dir))
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0


def cmd_mvp_ui_approvals_approve(args: argparse.Namespace) -> int:
    out = ui1_approve(data_dir=str(args.data_dir), approval_id=str(args.approval_id), replay_mode=bool(args.replay_mode))
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0 if out.get("ok") else 1


def cmd_mvp_ui_approvals_reject(args: argparse.Namespace) -> int:
    out = ui1_reject(data_dir=str(args.data_dir), approval_id=str(args.approval_id), replay_mode=bool(args.replay_mode))
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0 if out.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentos-next")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_mvp = sub.add_parser("mvp", help="MVP utilities")
    sub_mvp = p_mvp.add_subparsers(dest="mvp_cmd", required=True)

    p_run = sub_mvp.add_parser("run-skill", help="Run a single skill locally (MVP)")
    p_run.add_argument("--contract", required=True, help="Path to skill contract (.json or .skill/.yaml)")
    p_run.add_argument("--input", default="{}", help="JSON object string (default: {})")
    p_run.add_argument("--input-file", help="Path to JSON file containing the input object")
    p_run.add_argument("--workspace-id", default="local", help="Workspace identifier (default: local)")
    p_run.add_argument("--data-dir", default="data", help="Output data dir for evidence/trace (default: ./data)")
    p_run.add_argument("--trace-id")
    p_run.add_argument("--turn-id")
    p_run.add_argument("--span-id")
    p_run.add_argument("--parent-span-id")
    p_run.set_defaults(_fn=cmd_mvp_run_skill)

    p_pkg = sub_mvp.add_parser("run-package", help="Run a signed skill package via LLM backend (MVP)")
    p_pkg.add_argument("--skill-dir", required=True, help="Path to a skill package directory")
    p_pkg.add_argument("--keys-dir", help="Directory containing <signer_id>.pub (required when --verify-asvp)")
    p_pkg.add_argument("--verify-asvp", action="store_true", help="Verify manifest+signature (ASVP)")
    p_pkg.add_argument("--no-verify-asvp", dest="verify_asvp", action="store_false", help="Disable ASVP verification")
    p_pkg.set_defaults(verify_asvp=True)
    p_pkg.add_argument("--backend", default="local_mock", help="local_mock|codex_oauth|doubao_ark|minimax (default: local_mock)")
    p_pkg.add_argument("--remote-calls-armed", action="store_true", help="Arm remote calls (double gate)")
    p_pkg.add_argument("--allow-network-egress", action="store_true", help="Allow network egress (double gate)")
    p_pkg.add_argument("--approved-by-human", action="store_true", help="Mark HITL as approved")
    p_pkg.add_argument("--replay-mode", action="store_true", help="Forbid any remote calls regardless of gates")
    p_pkg.add_argument("--input", default="{}", help="JSON object string (default: {})")
    p_pkg.add_argument("--input-file", help="Path to JSON file containing the input object")
    p_pkg.add_argument("--workspace-id", default="local", help="Workspace identifier (default: local)")
    p_pkg.add_argument("--data-dir", default="data", help="Output data dir for evidence/trace (default: ./data)")
    p_pkg.add_argument("--trace-id")
    p_pkg.add_argument("--turn-id")
    p_pkg.add_argument("--span-id")
    p_pkg.add_argument("--parent-span-id")
    p_pkg.set_defaults(_fn=cmd_mvp_run_package)

    p_trace = sub_mvp.add_parser("trace-view", help="Export a replayable execution view for one trace or PA event")
    p_trace.add_argument("--data-dir", default="data", help="Data dir containing traces/, evidence/, pa/ and idempotency/")
    p_trace.add_argument("--trace-id", help="Trace ID to inspect")
    p_trace.add_argument("--turn-id", help="Optional turn ID filter")
    p_trace.add_argument("--event-id", help="Optional PA event_id, e.g. tg_update_299891376")
    p_trace.add_argument("--workspace-id", default="local", help="Workspace ID for PA event/outbox/task graph files")
    p_trace.add_argument("--html-out", nargs="?", const="auto", help="Write a self-contained HTML report (optional path, default: <data-dir>/trace_views/<trace>.html)")
    p_trace.set_defaults(_fn=cmd_mvp_trace_view)

    p_trace_serve = sub_mvp.add_parser("trace-serve", help="Serve an interactive trace viewer on loopback")
    p_trace_serve.add_argument("--data-dir", default="data", help="Data dir containing traces/, evidence/, pa/ and idempotency/")
    p_trace_serve.add_argument("--host", default="127.0.0.1", help="Bind host (loopback only)")
    p_trace_serve.add_argument("--port", default=8766, type=int, help="Bind port (default: 8766)")
    p_trace_serve.add_argument("--max-requests", type=int, default=None, help="Stop server after N requests (useful for tests)")
    p_trace_serve.set_defaults(_fn=cmd_mvp_trace_serve)

    p_exec = sub_mvp.add_parser("exec", help="Run ExecuteRequest via orchestrator->executor (MVP)")
    p_exec.add_argument(
        "--operator-ref",
        "--skill-ref",
        dest="operator_ref",
        required=True,
        help="Operator reference: path to a skill package directory, or builtin://memory.{write,search,compact,delete}",
    )
    p_exec.add_argument("--keys-dir", help="Directory containing <signer_id>.pub (required when --verify-asvp)")
    p_exec.add_argument("--verify-asvp", action="store_true", help="Verify manifest+signature (ASVP)")
    p_exec.add_argument("--no-verify-asvp", dest="verify_asvp", action="store_false", help="Disable ASVP verification")
    p_exec.set_defaults(verify_asvp=True)
    p_exec.add_argument(
        "--target",
        default="auto",
        choices=["auto", "local", "remote"],
        help="Execution target: auto|local|remote (default: auto)",
    )
    p_exec.add_argument("--backend", default="local_mock", help="local_mock|codex_oauth|doubao_ark|minimax (default: local_mock)")
    p_exec.add_argument(
        "--model",
        default=None,
        help="Model ID override (e.g., gpt-4, o3). Overrides skill's execution_profile.model_id",
    )
    p_exec.add_argument("--remote-calls-armed", action="store_true", help="Arm remote calls (double gate)")
    p_exec.add_argument("--allow-network-egress", action="store_true", help="Allow network egress (double gate)")
    p_exec.add_argument("--approved-by-human", action="store_true", help="Mark HITL as approved")
    p_exec.add_argument("--replay-mode", action="store_true", help="Forbid any remote calls regardless of gates")
    p_exec.add_argument("--arguments", "--input", dest="arguments", default="{}", help="JSON object string (default: {})")
    p_exec.add_argument("--arguments-file", "--input-file", dest="arguments_file", help="Path to JSON file containing the arguments object")
    p_exec.add_argument("--workspace-id", default="local", help="Workspace identifier (default: local)")
    p_exec.add_argument("--data-dir", default="data", help="Output data dir for evidence/trace (default: ./data)")
    p_exec.add_argument("--idempotency-key", help="Idempotency key (default: auto-generate)")
    p_exec.add_argument("--deadline-ms", default=60000, type=int, help="Deadline in milliseconds (default: 60000)")
    p_exec.add_argument(
        "--budget-slice",
        default=None,
        type=int,
        help="Budget slice (v1: remote_llm_calls). Unset means unlimited (default: unset).",
    )
    p_exec.add_argument("--trace-id")
    p_exec.add_argument("--turn-id")
    p_exec.add_argument("--span-id")
    p_exec.add_argument("--parent-span-id")
    p_exec.set_defaults(_fn=cmd_mvp_exec)

    p_reg_add = sub_mvp.add_parser("registry-add", help="Spike-REG1: add a skill package to local registry index")
    p_reg_add.add_argument("--skill-dir", required=True, help="Path to a signed skill package directory")
    p_reg_add.add_argument("--data-dir", default="data", help="Data dir for registry index/evidence (default: ./data)")
    p_reg_add.add_argument(
        "--deps-json",
        default=None,
        help='REG2: JSON array of registryq:// deps to attach to this entry (example: ["registryq://foo@1.2.3"])',
    )
    p_reg_add.set_defaults(_fn=cmd_mvp_registry_add)

    p_reg_res = sub_mvp.add_parser("registry-resolve", help="REG2: resolve a registryq:// query ref to registry://")
    p_reg_res.add_argument("--ref", required=True, help="Query ref: registryq://<name>@<constraint>")
    p_reg_res.add_argument("--with-deps", action="store_true", help="Also resolve deps graph declared on the entry")
    p_reg_res.add_argument("--data-dir", default="data", help="Data dir for registry index/evidence (default: ./data)")
    p_reg_res.set_defaults(_fn=cmd_mvp_registry_resolve)

    p_sched_tick = sub_mvp.add_parser("scheduler-tick", help="Spike-SCHED1: fire due scheduled tasks (explicit runner)")
    p_sched_tick.add_argument("--data-dir", default="data", help="Data dir for scheduler/evidence/trace (default: ./data)")
    p_sched_tick.add_argument("--now", default=None, help="UTC ISO time override for deterministic tick (default: now)")
    p_sched_tick.add_argument("--max-fires", type=int, default=50, help="Max tasks to fire per tick (default: 50)")
    p_sched_tick.add_argument("--remote-calls-armed", action="store_true", help="Arm remote calls (double gate)")
    p_sched_tick.add_argument("--allow-network-egress", action="store_true", help="Allow network egress (double gate)")
    p_sched_tick.add_argument("--approved-by-human", action="store_true", help="Mark HITL as approved")
    p_sched_tick.add_argument("--replay-mode", action="store_true", help="Forbid any remote calls regardless of gates")
    p_sched_tick.add_argument("--trace-id")
    p_sched_tick.add_argument("--turn-id")
    p_sched_tick.add_argument("--span-id")
    p_sched_tick.add_argument("--parent-span-id")
    p_sched_tick.set_defaults(_fn=cmd_mvp_scheduler_tick)

    p_daemon = sub_mvp.add_parser("daemon", help="Spike-DM2: daemon runner with single-writer + WAL + heartbeat")
    sub_daemon = p_daemon.add_subparsers(dest="daemon_cmd", required=True)

    p_daemon_status = sub_daemon.add_parser("status", help="Print daemon health/status snapshot")
    p_daemon_status.add_argument("--data-dir", default="data", help="Data dir for daemon/scheduler state (default: ./data)")
    p_daemon_status.set_defaults(_fn=cmd_mvp_daemon_status)

    p_daemon_once = sub_daemon.add_parser("run-once", help="Run one daemon tick cycle")
    p_daemon_once.add_argument("--data-dir", default="data", help="Data dir for daemon/scheduler state (default: ./data)")
    p_daemon_once.add_argument("--tick-interval-ms", type=int, default=1000, help="Tick interval in ms (default: 1000)")
    p_daemon_once.add_argument("--max-fires", type=int, default=50, help="Max tasks to fire in one tick (default: 50)")
    p_daemon_once.add_argument("--now", default=None, help="UTC ISO time override for deterministic run-once")
    p_daemon_once.add_argument("--strict-mode", action="store_true", help="Block on first internal daemon error")
    p_daemon_once.add_argument("--remote-calls-armed", action="store_true", help="Arm remote calls (double gate)")
    p_daemon_once.add_argument("--allow-network-egress", action="store_true", help="Allow network egress (double gate)")
    p_daemon_once.add_argument("--approved-by-human", action="store_true", help="Mark HITL as approved")
    p_daemon_once.add_argument("--replay-mode", action="store_true", help="DM2 policy: forbid daemon execution in replay mode")
    p_daemon_once.set_defaults(_fn=cmd_mvp_daemon_run_once)

    p_daemon_run = sub_daemon.add_parser("run", help="Run daemon loop")
    p_daemon_run.add_argument("--data-dir", default="data", help="Data dir for daemon/scheduler state (default: ./data)")
    p_daemon_run.add_argument("--tick-interval-ms", type=int, default=1000, help="Tick interval in ms (default: 1000)")
    p_daemon_run.add_argument("--max-fires", type=int, default=50, help="Max tasks to fire per tick (default: 50)")
    p_daemon_run.add_argument("--max-loops", type=int, default=None, help="Optional loop cap for tests")
    p_daemon_run.add_argument("--now", default=None, help="UTC ISO time override used for each loop")
    p_daemon_run.add_argument("--strict-mode", action="store_true", help="Block on first internal daemon error")
    p_daemon_run.add_argument("--remote-calls-armed", action="store_true", help="Arm remote calls (double gate)")
    p_daemon_run.add_argument("--allow-network-egress", action="store_true", help="Allow network egress (double gate)")
    p_daemon_run.add_argument("--approved-by-human", action="store_true", help="Mark HITL as approved")
    p_daemon_run.add_argument("--replay-mode", action="store_true", help="DM2 policy: forbid daemon execution in replay mode")
    p_daemon_run.set_defaults(_fn=cmd_mvp_daemon_run)

    p_si1_obs = sub_mvp.add_parser("si1-observe", help="SI1 Phase-1: observe evidence/trace and emit signals.json")
    p_si1_obs.add_argument("--data-dir", default="data", help="Data dir to scan and write SI1 outputs (default: ./data)")
    p_si1_obs.add_argument("--run-id", default=None, help="Optional run id (default: auto)")
    p_si1_obs.add_argument("--replay-mode", action="store_true", help="No side effects (no writes) for SI1")
    p_si1_obs.set_defaults(_fn=cmd_mvp_si1_observe)

    p_si1_prop = sub_mvp.add_parser("si1-propose", help="SI1 Phase-1: propose a deterministic plan from signals.json")
    p_si1_prop.add_argument("--data-dir", default="data", help="Data dir that contains SI1 run outputs (default: ./data)")
    p_si1_prop.add_argument("--run-id", required=True, help="Run id to load (expects data/si1/runs/<run_id>/signals.json)")
    p_si1_prop.add_argument("--replay-mode", action="store_true", help="No side effects (no writes) for SI1")
    p_si1_prop.set_defaults(_fn=cmd_mvp_si1_propose)

    p_si1_val = sub_mvp.add_parser("si1-validate", help="SI1 Phase-1: validate proposal by running unittest (full)")
    p_si1_val.add_argument("--data-dir", default="data", help="Data dir that contains SI1 run outputs (default: ./data)")
    p_si1_val.add_argument("--run-id", required=True, help="Run id to validate (writes validation.json)")
    p_si1_val.add_argument("--replay-mode", action="store_true", help="No side effects (no writes) for SI1")
    p_si1_val.set_defaults(_fn=cmd_mvp_si1_validate)

    p_chan = sub_mvp.add_parser("channel-stdio", help="Spike-OC1: stdin channel adapter (MVP)")
    p_chan.add_argument(
        "--operator-ref",
        "--skill-ref",
        dest="operator_ref",
        help="Operator reference (path for MVP). Default: examples/skills/personal_assistant_brief",
    )
    p_chan.add_argument(
        "--keys-dir",
        help="Directory containing <signer_id>.pub (required when --verify-asvp; default: repo examples)",
    )
    p_chan.add_argument("--verify-asvp", action="store_true", help="Verify manifest+signature (ASVP)")
    p_chan.add_argument("--no-verify-asvp", dest="verify_asvp", action="store_false", help="Disable ASVP verification")
    p_chan.set_defaults(verify_asvp=True)
    p_chan.add_argument(
        "--target",
        default="auto",
        choices=["auto", "local", "remote"],
        help="Execution target: auto|local|remote (default: auto)",
    )
    p_chan.add_argument("--backend", default="local_mock", help="local_mock|codex_oauth|doubao_ark|minimax (default: local_mock)")
    p_chan.add_argument("--model", default=None, help="Model ID override (optional)")
    p_chan.add_argument("--remote-calls-armed", action="store_true", help="Arm remote calls (double gate)")
    p_chan.add_argument("--allow-network-egress", action="store_true", help="Allow network egress (double gate)")
    p_chan.add_argument("--approved-by-human", action="store_true", help="Mark HITL as approved")
    p_chan.add_argument("--replay-mode", action="store_true", help="Forbid any remote calls regardless of gates")
    p_chan.add_argument("--workspace-id", default="local", help="Workspace identifier (default: local)")
    p_chan.add_argument("--data-dir", default="data", help="Output data dir for evidence/trace (default: ./data)")
    p_chan.add_argument("--trace-id", help="Stable trace_id to reuse across all turns in this session")
    p_chan.add_argument("--deadline-ms", default=60000, type=int, help="Per-turn deadline in ms (default: 60000)")
    p_chan.add_argument("--json-lines", action="store_true", help="Read JSON lines: {arguments|message, idempotency_key?}")
    p_chan.add_argument("--max-turns", type=int, help="Stop after N turns (useful for tests)")
    p_chan.set_defaults(_fn=cmd_mvp_channel_stdio)

    p_chan_http = sub_mvp.add_parser("channel-http", help="Spike-CH1: local HTTP gateway channel (P0)")
    p_chan_http.add_argument("--host", default="127.0.0.1", help="Bind host (P0 restricted to loopback)")
    p_chan_http.add_argument("--port", default=8765, type=int, help="Bind port (default: 8765)")
    p_chan_http.add_argument("--max-requests", type=int, help="Stop server after N requests (useful for tests)")
    p_chan_http.add_argument(
        "--operator-ref",
        "--skill-ref",
        dest="operator_ref",
        help="Operator reference (path for MVP). Default: examples/skills/personal_assistant_brief",
    )
    p_chan_http.add_argument(
        "--keys-dir",
        help="Directory containing <signer_id>.pub (required when --verify-asvp; default: repo examples)",
    )
    p_chan_http.add_argument("--verify-asvp", action="store_true", help="Verify manifest+signature (ASVP)")
    p_chan_http.add_argument("--no-verify-asvp", dest="verify_asvp", action="store_false", help="Disable ASVP verification")
    p_chan_http.set_defaults(verify_asvp=True)
    p_chan_http.add_argument(
        "--target",
        default="auto",
        choices=["auto", "local", "remote"],
        help="Execution target: auto|local|remote (default: auto)",
    )
    p_chan_http.add_argument("--backend", default="local_mock", help="local_mock|codex_oauth|doubao_ark|minimax (default: local_mock)")
    p_chan_http.add_argument("--model", default=None, help="Model ID override (optional)")
    p_chan_http.add_argument("--remote-calls-armed", action="store_true", help="Arm remote calls (double gate)")
    p_chan_http.add_argument("--allow-network-egress", action="store_true", help="Allow network egress (double gate)")
    p_chan_http.add_argument("--approved-by-human", action="store_true", help="Mark HITL as approved")
    p_chan_http.add_argument("--replay-mode", action="store_true", help="Forbid any remote calls regardless of gates")
    p_chan_http.add_argument("--workspace-id", default="local", help="Workspace identifier (default: local)")
    p_chan_http.add_argument("--data-dir", default="data", help="Output data dir for evidence/trace (default: ./data)")
    p_chan_http.add_argument("--deadline-ms", default=60000, type=int, help="Per-turn deadline in ms (default: 60000)")
    p_chan_http.set_defaults(_fn=cmd_mvp_channel_http)

    p_eval_memory = sub_mvp.add_parser("eval-memory", help="THREAD-022: memory effect A/B/C evaluation harness")
    p_eval_memory.add_argument("--dataset", required=True, help="Path to memory-effect JSONL dataset")
    p_eval_memory.add_argument(
        "--strategy",
        default="A",
        choices=["A", "B", "C", "a", "b", "c"],
        help="Evaluation strategy: A|B|C (default: A)",
    )
    p_eval_memory.add_argument("--out", help="Optional path to write report JSON")
    p_eval_memory.add_argument("--seed", default=0, type=int, help="Deterministic seed (default: 0)")
    p_eval_memory.set_defaults(_fn=cmd_mvp_eval_memory)

    p_eval_memory_compare = sub_mvp.add_parser(
        "eval-memory-compare", help="THREAD-022: compare A/B/C memory-effect reports and pick winner"
    )
    p_eval_memory_compare.add_argument("--report-a", required=True, help="Path to strategy A report JSON")
    p_eval_memory_compare.add_argument("--report-b", required=True, help="Path to strategy B report JSON")
    p_eval_memory_compare.add_argument("--report-c", required=True, help="Path to strategy C report JSON")
    p_eval_memory_compare.add_argument(
        "--baseline-strategy",
        default="A",
        choices=["A", "B", "C", "a", "b", "c"],
        help="Baseline strategy for guard checks (default: A)",
    )
    p_eval_memory_compare.add_argument(
        "--guard-epsilon",
        default=0.0,
        type=float,
        help="Float epsilon for guard comparisons (default: 0.0)",
    )
    p_eval_memory_compare.add_argument("--out", help="Optional path to write comparison JSON")
    p_eval_memory_compare.set_defaults(_fn=cmd_mvp_eval_memory_compare)

    p_creator = sub_mvp.add_parser("creator-plan", help="Spike-CR1: compile-aware discovery + plan-only compose")
    p_creator.add_argument("--registry-root", required=True, help="Root directory that contains compiled skill outputs")
    p_creator.add_argument("--intent", required=True, help="User intent to compose against discovered skills")
    p_creator.add_argument("--workspace-id", default="local", help="Workspace identifier (default: local)")
    p_creator.add_argument("--deadline-ms", default=60000, type=int, help="Deadline in ms for request draft")
    p_creator.add_argument("--max-steps", default=3, type=int, help="Max steps in composed plan (default: 3)")
    p_creator.add_argument("--model", default=None, help="Model override passed into plan.policy_context.model")
    p_creator.add_argument("--plan-out", help="Optional path to write plan JSON")
    p_creator.set_defaults(_fn=cmd_mvp_creator_plan)

    p_ui_once = sub_mvp.add_parser("ui-run-once", help="THREAD-021: UI1 acceptance shell run-once (P0)")
    p_ui_once.add_argument("--message", required=True, help="User message")
    p_ui_once.add_argument(
        "--operator-ref",
        "--skill-ref",
        dest="operator_ref",
        default=str(_repo_root() / "examples" / "skills" / "personal_assistant_brief"),
        help="Operator reference (path for MVP). Default: examples/skills/personal_assistant_brief",
    )
    p_ui_once.add_argument("--keys-dir", help="Directory containing <signer_id>.pub (required when --verify-asvp)")
    p_ui_once.add_argument("--verify-asvp", action="store_true", help="Verify manifest+signature (ASVP)")
    p_ui_once.add_argument("--no-verify-asvp", dest="verify_asvp", action="store_false", help="Disable ASVP verification")
    p_ui_once.set_defaults(verify_asvp=True)
    p_ui_once.add_argument("--backend", default="local_mock", help="local_mock|codex_oauth|doubao_ark|minimax (default: local_mock)")
    p_ui_once.add_argument("--model", default=None, help="Model override passed into policy_context[\"model\"]")
    p_ui_once.add_argument("--target", default="auto", choices=["auto", "local", "remote"], help="preferred_target")
    p_ui_once.add_argument("--remote-calls-armed", action="store_true", help="Arm remote calls (double gate)")
    p_ui_once.add_argument("--allow-network-egress", action="store_true", help="Allow network egress (double gate)")
    p_ui_once.add_argument("--approved-by-human", action="store_true", help="Mark HITL as approved")
    p_ui_once.add_argument("--replay-mode", action="store_true", help="UI1 policy: zero-write + no execution in replay-mode")
    p_ui_once.add_argument("--workspace-id", default="local", help="Workspace identifier (default: local)")
    p_ui_once.add_argument("--data-dir", default="data", help="Output data dir for evidence/trace (default: ./data)")
    p_ui_once.add_argument("--deadline-ms", default=60000, type=int, help="Deadline in milliseconds (default: 60000)")
    p_ui_once.add_argument("--trace-id")
    p_ui_once.add_argument("--turn-id")
    p_ui_once.add_argument("--span-id")
    p_ui_once.add_argument("--parent-span-id")
    p_ui_once.add_argument("--idempotency-key")
    p_ui_once.set_defaults(_fn=cmd_mvp_ui_run_once)

    p_ui_appr = sub_mvp.add_parser("ui-approvals", help="THREAD-021: UI1 HITL approvals store (local-only)")
    sub_ui_appr = p_ui_appr.add_subparsers(dest="ui_approvals_cmd", required=True)

    p_ui_list = sub_ui_appr.add_parser("list", help="List approvals")
    p_ui_list.add_argument("--data-dir", default="data", help="Data dir (default: ./data)")
    p_ui_list.set_defaults(_fn=cmd_mvp_ui_approvals_list)

    p_ui_approve = sub_ui_appr.add_parser("approve", help="Approve an approval id and rerun")
    p_ui_approve.add_argument("--data-dir", default="data", help="Data dir (default: ./data)")
    p_ui_approve.add_argument("--approval-id", required=True, help="Approval identifier")
    p_ui_approve.add_argument("--replay-mode", action="store_true", help="UI1 policy: zero-write + no execution in replay-mode")
    p_ui_approve.set_defaults(_fn=cmd_mvp_ui_approvals_approve)

    p_ui_reject = sub_ui_appr.add_parser("reject", help="Reject an approval id")
    p_ui_reject.add_argument("--data-dir", default="data", help="Data dir (default: ./data)")
    p_ui_reject.add_argument("--approval-id", required=True, help="Approval identifier")
    p_ui_reject.add_argument("--replay-mode", action="store_true", help="UI1 policy: zero-write + no execution in replay-mode")
    p_ui_reject.set_defaults(_fn=cmd_mvp_ui_approvals_reject)

    p_demo = sub_mvp.add_parser("assistant-demo", help="Run a personal assistant demo (MVP)")
    p_demo.add_argument("--query", required=True, help="User query (e.g. '总结今天的热点八卦')")
    p_demo.add_argument("--skill-dir", help="Path to a demo skill package directory (default: repo examples)")
    p_demo.add_argument("--keys-dir", help="Directory containing <signer_id>.pub (default: repo examples)")
    p_demo.add_argument("--verify-asvp", action="store_true", help="Verify manifest+signature (ASVP)")
    p_demo.add_argument("--no-verify-asvp", dest="verify_asvp", action="store_false", help="Disable ASVP verification")
    p_demo.set_defaults(verify_asvp=True)
    p_demo.add_argument("--backend", default="local_mock", help="local_mock|codex_oauth|doubao_ark|minimax (default: local_mock)")
    p_demo.add_argument("--intent-backend", default=None, help="Intent router backend override (e.g. doubao_ark)")
    p_demo.add_argument("--intent-model", default=None, help="Intent router model/endpoint override")
    p_demo.add_argument("--communicator-backend", default=None, help="Communicator backend override (e.g. doubao_ark)")
    p_demo.add_argument("--communicator-model", default=None, help="Communicator model/endpoint override")
    p_demo.add_argument("--response-language", default=None, help="Preferred language for user-visible replies (e.g. zh-CN)")
    p_demo.add_argument("--remote-calls-armed", action="store_true", help="Arm remote calls (double gate)")
    p_demo.add_argument("--allow-network-egress", action="store_true", help="Allow network egress (double gate)")
    p_demo.add_argument("--approved-by-human", action="store_true", help="Mark HITL as approved")
    p_demo.add_argument("--replay-mode", action="store_true", help="Forbid any remote calls regardless of gates")
    p_demo.add_argument("--workspace-id", default="local", help="Workspace identifier (default: local)")
    p_demo.add_argument("--data-dir", default="data", help="Output data dir for evidence/trace (default: ./data)")
    p_demo.add_argument("--trace-id")
    p_demo.add_argument("--turn-id")
    p_demo.add_argument("--span-id")
    p_demo.add_argument("--parent-span-id")
    p_demo.add_argument("--model-id", help="LLM model identifier")
    p_demo.set_defaults(_fn=cmd_mvp_assistant_demo)

    p_pa_demo = sub_mvp.add_parser(
        "pa-demo",
        help="THREAD-040: visible Telegram PA roundtrip demo (webhook -> canonical runtime -> outbox -> reply stub)",
    )
    p_pa_demo.add_argument(
        "--payload-file",
        help="Path to Telegram webhook JSON file (default: examples/fixtures/telegram_webhook_sample.json)",
    )
    p_pa_demo.add_argument("--payload", help="Raw Telegram webhook JSON string (overrides --payload-file)")
    p_pa_demo.add_argument(
        "--expected-secret-token",
        default="demo-secret",
        help="Expected Telegram secret token (default: demo-secret)",
    )
    p_pa_demo.add_argument(
        "--secret-token",
        default=None,
        help="Provided secret token (default: same as --expected-secret-token)",
    )
    p_pa_demo.add_argument("--workspace-id", default="local", help="Workspace identifier (default: local)")
    p_pa_demo.add_argument("--data-dir", default="data", help="Output data dir for evidence/trace (default: ./data)")
    p_pa_demo.add_argument(
        "--budget-slice-remote-llm-calls",
        dest="budget_slice_remote_llm_calls",
        default=None,
        type=int,
        help="Optional override for envelope budget (missing => fallback=10; v1 unit: remote_llm_calls)",
    )
    p_pa_demo.add_argument("--replay-mode", action="store_true", help="Strict replay deny for visible demo (zero-write)")
    p_pa_demo.add_argument(
        "--operator-ref",
        "--skill-ref",
        dest="operator_ref",
        help="Operator reference / skill package directory (default: examples/skills/personal_assistant_brief)",
    )
    p_pa_demo.add_argument(
        "--keys-dir",
        help="Directory containing <signer_id>.pub (default: examples/keys)",
    )
    p_pa_demo.add_argument("--verify-asvp", action="store_true", help="Verify manifest+signature (ASVP)")
    p_pa_demo.add_argument("--no-verify-asvp", dest="verify_asvp", action="store_false", help="Disable ASVP verification")
    p_pa_demo.set_defaults(verify_asvp=True)
    p_pa_demo.add_argument("--backend", default="local_mock", help="local_mock|codex_oauth|doubao_ark|minimax (default: local_mock)")
    p_pa_demo.add_argument("--model", default=None, help="Model override passed into policy_context[\"model\"]")
    p_pa_demo.add_argument(
        "--target",
        default="local",
        choices=["auto", "local", "remote"],
        help="Execution target: auto|local|remote (default: local)",
    )
    p_pa_demo.add_argument("--remote-calls-armed", action="store_true", help="Arm remote calls (double gate)")
    p_pa_demo.add_argument("--allow-network-egress", action="store_true", help="Allow network egress (double gate)")
    p_pa_demo.add_argument("--approved-by-human", action="store_true", help="Mark HITL as approved")
    p_pa_demo.add_argument("--deadline-ms", default=60000, type=int, help="Per-turn deadline in ms (default: 60000)")
    p_pa_demo.add_argument(
        "--message-input-key",
        default="request",
        help="Map inbound message_text into ExecuteRequest.input via this key (default: request)",
    )
    p_pa_demo.add_argument(
        "--memory-context-enabled",
        action="store_true",
        help="Enable Memory V2 context assembly",
    )
    p_pa_demo.add_argument(
        "--memory-context-retrieval-limit",
        default=8,
        type=int,
        help="Max number of Memory V2 hits to inject (default: 8)",
    )
    p_pa_demo.add_argument(
        "--memory-context-include-stale",
        action="store_true",
        help="Allow stale Memory V2 hits during retrieval",
    )
    p_pa_demo.add_argument(
        "--memory-context-continuity-event-limit",
        default=50,
        type=int,
        help="Max number of continuity events to reference in retrieval evidence (default: 50)",
    )
    p_pa_demo.add_argument(
        "--memory-context-audit-mode",
        action="store_true",
        help="Allow deleted Memory V2 records in audit/replay retrieval",
    )
    p_pa_demo.add_argument("--bot-token", default="stub-token", help="Telegram bot token (stub URL only)")
    p_pa_demo.set_defaults(_fn=cmd_mvp_pa_demo)

    p_pa_webhook = sub_mvp.add_parser(
        "pa-webhook-server",
        help="THREAD-041: loopback Telegram webhook server (webhook -> canonical runtime -> outbox -> reply stub)",
    )
    p_pa_webhook.add_argument("--host", default="127.0.0.1", help="Bind host (loopback only)")
    p_pa_webhook.add_argument("--port", default=8089, type=int, help="Bind port (default: 8089)")
    p_pa_webhook.add_argument("--path", default="/v1/telegram/webhook", help="Webhook path")
    p_pa_webhook.add_argument("--max-requests", default=None, type=int, help="Stop server after N requests")
    p_pa_webhook.add_argument(
        "--expected-secret-token",
        required=True,
        help="Expected value for X-Telegram-Bot-Api-Secret-Token",
    )
    p_pa_webhook.add_argument("--workspace-id", default="local", help="Workspace identifier (default: local)")
    p_pa_webhook.add_argument(
        "--routing-file",
        default=None,
        help="Optional JSON file mapping conversation/chat IDs to workspace_id (+ optional budget)",
    )
    p_pa_webhook.add_argument("--data-dir", default="data", help="Output data dir for evidence/trace (default: ./data)")
    p_pa_webhook.add_argument(
        "--budget-slice-remote-llm-calls",
        dest="budget_slice_remote_llm_calls",
        default=None,
        type=int,
        help="Optional override for envelope budget (missing => fallback=10; v1 unit: remote_llm_calls)",
    )
    p_pa_webhook.add_argument("--replay-mode", action="store_true", help="Strict replay deny (zero-write)")
    p_pa_webhook.add_argument(
        "--operator-ref",
        "--skill-ref",
        dest="operator_ref",
        help="Operator reference / skill package directory (default: examples/skills/personal_assistant_brief)",
    )
    p_pa_webhook.add_argument("--keys-dir", help="Directory containing <signer_id>.pub (required with --verify-asvp)")
    p_pa_webhook.add_argument("--verify-asvp", action="store_true", help="Verify manifest+signature (ASVP)")
    p_pa_webhook.add_argument(
        "--no-verify-asvp",
        dest="verify_asvp",
        action="store_false",
        help="Disable ASVP verification",
    )
    p_pa_webhook.set_defaults(verify_asvp=True)
    p_pa_webhook.add_argument("--backend", default="local_mock", help="local_mock|codex_oauth|doubao_ark|minimax (default: local_mock)")
    p_pa_webhook.add_argument("--model", default=None, help="Model override passed into policy_context[\"model\"]")
    p_pa_webhook.add_argument(
        "--target",
        default="local",
        choices=["auto", "local", "remote"],
        help="Execution target: auto|local|remote (default: local)",
    )
    p_pa_webhook.add_argument("--remote-calls-armed", action="store_true", help="Arm remote calls (double gate)")
    p_pa_webhook.add_argument("--allow-network-egress", action="store_true", help="Allow network egress (double gate)")
    p_pa_webhook.add_argument("--approved-by-human", action="store_true", help="Mark HITL as approved")
    p_pa_webhook.add_argument("--deadline-ms", default=60000, type=int, help="Per-turn deadline in ms (default: 60000)")
    p_pa_webhook.add_argument(
        "--message-input-key",
        default="request",
        help="Map inbound message_text into ExecuteRequest.input via this key (default: request)",
    )
    p_pa_webhook.add_argument(
        "--memory-context-enabled",
        action="store_true",
        help="Enable Memory V2 context assembly",
    )
    p_pa_webhook.add_argument(
        "--memory-context-retrieval-limit",
        default=8,
        type=int,
        help="Max number of Memory V2 hits to inject (default: 8)",
    )
    p_pa_webhook.add_argument(
        "--memory-context-include-stale",
        action="store_true",
        help="Allow stale Memory V2 hits during retrieval",
    )
    p_pa_webhook.add_argument(
        "--memory-context-continuity-event-limit",
        default=50,
        type=int,
        help="Max number of continuity events to reference in retrieval evidence (default: 50)",
    )
    p_pa_webhook.add_argument(
        "--memory-context-audit-mode",
        action="store_true",
        help="Allow deleted Memory V2 records in audit/replay retrieval",
    )
    p_pa_webhook.add_argument("--bot-token", default="stub-token", help="Telegram bot token (stub URL only)")
    p_pa_webhook.set_defaults(_fn=cmd_mvp_pa_webhook_server)

    p_pa_polling = sub_mvp.add_parser(
        "pa-polling",
        help="THREAD-044: local Telegram polling mode (getUpdates -> canonical runtime -> outbox -> reply)",
    )
    p_pa_polling.add_argument("--bot-token", default=None, help="Telegram bot token")
    p_pa_polling.add_argument("--workspace-id", default="local", help="Workspace identifier (default: local)")
    p_pa_polling.add_argument(
        "--routing-file",
        default=None,
        help="Optional JSON file mapping conversation/chat IDs to workspace_id (+ optional budget)",
    )
    p_pa_polling.add_argument("--data-dir", default="data", help="Output data dir for evidence/trace (default: ./data)")
    p_pa_polling.add_argument(
        "--budget-slice-remote-llm-calls",
        dest="budget_slice_remote_llm_calls",
        default=None,
        type=int,
        help="Optional override for envelope budget (missing => fallback=10; v1 unit: remote_llm_calls)",
    )
    p_pa_polling.add_argument("--replay-mode", action="store_true", help="Strict replay deny (zero-write)")
    p_pa_polling.add_argument(
        "--operator-ref",
        "--skill-ref",
        dest="operator_ref",
        help="Operator reference / skill package directory (default: examples/skills/personal_assistant_brief)",
    )
    p_pa_polling.add_argument("--keys-dir", help="Directory containing <signer_id>.pub (required with --verify-asvp)")
    p_pa_polling.add_argument("--verify-asvp", action="store_true", help="Verify manifest+signature (ASVP)")
    p_pa_polling.add_argument(
        "--no-verify-asvp",
        dest="verify_asvp",
        action="store_false",
        help="Disable ASVP verification",
    )
    p_pa_polling.set_defaults(verify_asvp=True)
    p_pa_polling.add_argument("--backend", default="local_mock", help="local_mock|codex_oauth|doubao_ark|minimax (default: local_mock)")
    p_pa_polling.add_argument("--intent-backend", default=None, help="Intent router backend override (e.g. doubao_ark)")
    p_pa_polling.add_argument("--intent-model", default=None, help="Intent router model/endpoint override")
    p_pa_polling.add_argument("--communicator-backend", default=None, help="Communicator backend override (e.g. doubao_ark)")
    p_pa_polling.add_argument("--communicator-model", default=None, help="Communicator model/endpoint override")
    p_pa_polling.add_argument("--response-language", default=None, help="Preferred language for user-visible replies (e.g. zh-CN)")
    p_pa_polling.add_argument(
        "--capabilities",
        default="",
        help="Comma-separated capability names (THREAD-030); auto-adds llm_remote/net_egress for remote flags",
    )
    p_pa_polling.add_argument("--model", default=None, help="Model override passed into policy_context[\"model\"]")
    p_pa_polling.add_argument(
        "--target",
        default="local",
        choices=["auto", "local", "remote"],
        help="Execution target: auto|local|remote (default: local)",
    )
    p_pa_polling.add_argument("--remote-calls-armed", action="store_true", help="Arm remote calls (double gate)")
    p_pa_polling.add_argument("--allow-network-egress", action="store_true", help="Allow network egress (double gate)")
    p_pa_polling.add_argument("--approved-by-human", action="store_true", help="Mark HITL as approved")
    p_pa_polling.add_argument("--deadline-ms", default=60000, type=int, help="Per-turn deadline in ms (default: 60000)")
    p_pa_polling.add_argument(
        "--message-input-key",
        default="request",
        help="Map inbound message_text into ExecuteRequest.input via this key (default: request)",
    )
    p_pa_polling.add_argument(
        "--memory-context-enabled",
        action="store_true",
        help="Enable Memory V2 context assembly",
    )
    p_pa_polling.add_argument(
        "--memory-context-retrieval-limit",
        default=8,
        type=int,
        help="Max number of Memory V2 hits to inject (default: 8)",
    )
    p_pa_polling.add_argument(
        "--memory-context-include-stale",
        action="store_true",
        help="Allow stale Memory V2 hits during retrieval",
    )
    p_pa_polling.add_argument(
        "--memory-context-continuity-event-limit",
        default=50,
        type=int,
        help="Max number of continuity events to reference in retrieval evidence (default: 50)",
    )
    p_pa_polling.add_argument(
        "--memory-context-audit-mode",
        action="store_true",
        help="Allow deleted Memory V2 records in audit/replay retrieval",
    )
    p_pa_polling.add_argument("--offset", default=None, type=int, help="Telegram getUpdates offset (optional)")
    p_pa_polling.add_argument("--timeout-seconds", default=20, type=int, help="Long-poll timeout in seconds")
    p_pa_polling.add_argument("--limit", default=20, type=int, help="Max updates per poll cycle")
    p_pa_polling.add_argument(
        "--scheduler-auto-tick",
        dest="scheduler_auto_tick",
        action="store_true",
        help="Enable scheduler tick on each polling cycle (default: enabled)",
    )
    p_pa_polling.add_argument(
        "--no-scheduler-auto-tick",
        dest="scheduler_auto_tick",
        action="store_false",
        help="Disable scheduler tick on polling cycles",
    )
    p_pa_polling.set_defaults(scheduler_auto_tick=True)
    p_pa_polling.add_argument(
        "--scheduler-tick-max-fires",
        default=20,
        type=int,
        help="Max scheduled tasks fired per auto tick (default: 20)",
    )
    p_pa_polling.add_argument(
        "--max-cycles",
        default=1,
        type=int,
        help="Number of polling cycles to run (0 means run forever until interrupted)",
    )
    p_pa_polling.set_defaults(_fn=cmd_mvp_pa_polling)

    p_pa_login = sub_mvp.add_parser(
        "pa-login-openai",
        help="Perform OpenAI OAuth login (Codex mode) to get refresh_token",
    )
    p_pa_login.add_argument("--token-path", help="Path to save tokens")
    p_pa_login.add_argument("--client-id", default="app_EMoamEEZ73f0CkXaXp7hrann", help="OAuth client_id")
    p_pa_login.add_argument(
        "--redirect-uri",
        default="http://localhost:1455/auth/callback",
        help="OAuth redirect_uri",
    )
    p_pa_login.set_defaults(_fn=cmd_mvp_pa_login_openai)

    p_loop = sub_mvp.add_parser("assistant-loop", help="Spike-AL1: tool-calling multi-step assistant loop (MVP)")
    p_loop.add_argument("--query", required=True, help="User query")
    p_loop.add_argument(
        "--assistant-skill-dir",
        help="Path to assistant skill package (default: examples/skills/personal_assistant_brief)",
    )
    p_loop.add_argument("--keys-dir", help="Directory containing <signer_id>.pub (default: repo examples)")
    p_loop.add_argument("--verify-asvp", action="store_true", help="Verify manifest+signature (ASVP)")
    p_loop.add_argument("--no-verify-asvp", dest="verify_asvp", action="store_false", help="Disable ASVP verification")
    p_loop.set_defaults(verify_asvp=True)
    p_loop.add_argument("--backend", default="local_mock", help="local_mock|codex_oauth|doubao_ark|minimax (default: local_mock)")
    p_loop.add_argument(
        "--planner",
        default="deterministic",
        choices=["deterministic", "llm"],
        help="Planner mode: deterministic|llm (default: deterministic)",
    )
    p_loop.add_argument(
        "--planner-backend",
        default=None,
        help="Planner backend override (default: same as --backend). local_mock|codex_oauth|doubao_ark|minimax",
    )
    p_loop.add_argument("--model", default=None, help="Model override passed into policy_context[\"model\"]")
    p_loop.add_argument("--intent-backend", default=None, help="Intent router backend override (e.g. doubao_ark)")
    p_loop.add_argument("--intent-model", default=None, help="Intent router model/endpoint override")
    p_loop.add_argument("--communicator-backend", default=None, help="Communicator backend override (e.g. doubao_ark)")
    p_loop.add_argument("--communicator-model", default=None, help="Communicator model/endpoint override")
    p_loop.add_argument("--response-language", default=None, help="Preferred language for user-visible replies (e.g. zh-CN)")
    p_loop.add_argument("--remote-calls-armed", action="store_true", help="Arm remote calls (double gate)")
    p_loop.add_argument("--allow-network-egress", action="store_true", help="Allow network egress (double gate)")
    p_loop.add_argument("--approved-by-human", action="store_true", help="Mark HITL as approved")
    p_loop.add_argument("--replay-mode", action="store_true", help="Forbid any remote calls regardless of gates")
    p_loop.add_argument(
        "--capabilities",
        default="memory_write",
        help="Comma-separated capability names (THREAD-030); auto-adds llm_remote/net_egress for remote flags",
    )
    p_loop.add_argument("--workspace-id", default="local", help="Workspace identifier (default: local)")
    p_loop.add_argument("--data-dir", default="data", help="Output data dir for evidence/trace (default: ./data)")
    p_loop.add_argument("--idempotency-key", help="Idempotency key (default: derived from trace)")
    p_loop.add_argument("--deadline-ms", default=60000, type=int, help="Deadline in milliseconds (default: 60000)")
    p_loop.add_argument(
        "--runtime-mode",
        default="hybrid",
        choices=["direct", "hybrid"],
        help="Assistant runtime mode: direct|hybrid (default: hybrid)",
    )
    p_loop.add_argument(
        "--no-direct-fallback",
        dest="direct_fallback",
        action="store_false",
        help="Disable direct fallback when hybrid runtime fails",
    )
    p_loop.set_defaults(direct_fallback=True)
    p_loop.add_argument("--followup-at", default=None, help="FU2: schedule a follow-up run at this UTC ISO time")
    p_loop.add_argument("--trace-id")
    p_loop.add_argument("--turn-id")
    p_loop.add_argument("--span-id")
    p_loop.add_argument("--parent-span-id")
    p_loop.set_defaults(_fn=cmd_mvp_assistant_loop)

    p_loop_stdio = sub_mvp.add_parser(
        "assistant-loop-stdio",
        help="Spike-AL3: stdin-driven multi-step assistant loop (MVP)",
    )
    p_loop_stdio.add_argument(
        "--assistant-skill-dir",
        help="Path to assistant skill package (default: examples/skills/personal_assistant_brief)",
    )
    p_loop_stdio.add_argument("--keys-dir", help="Directory containing <signer_id>.pub (default: repo examples)")
    p_loop_stdio.add_argument("--verify-asvp", action="store_true", help="Verify manifest+signature (ASVP)")
    p_loop_stdio.add_argument(
        "--no-verify-asvp", dest="verify_asvp", action="store_false", help="Disable ASVP verification"
    )
    p_loop_stdio.set_defaults(verify_asvp=True)
    p_loop_stdio.add_argument("--backend", default="local_mock", help="local_mock|codex_oauth|doubao_ark|minimax (default: local_mock)")
    p_loop_stdio.add_argument(
        "--planner",
        default="deterministic",
        choices=["deterministic", "llm"],
        help="Planner mode: deterministic|llm (default: deterministic)",
    )
    p_loop_stdio.add_argument(
        "--planner-backend",
        default=None,
        help="Planner backend override (default: same as --backend). local_mock|codex_oauth|doubao_ark|minimax",
    )
    p_loop_stdio.add_argument("--model", default=None, help="Model override passed into policy_context[\"model\"]")
    p_loop_stdio.add_argument("--intent-backend", default=None, help="Intent router backend override (e.g. doubao_ark)")
    p_loop_stdio.add_argument("--intent-model", default=None, help="Intent router model/endpoint override")
    p_loop_stdio.add_argument("--communicator-backend", default=None, help="Communicator backend override (e.g. doubao_ark)")
    p_loop_stdio.add_argument("--communicator-model", default=None, help="Communicator model/endpoint override")
    p_loop_stdio.add_argument("--response-language", default=None, help="Preferred language for user-visible replies (e.g. zh-CN)")
    p_loop_stdio.add_argument("--remote-calls-armed", action="store_true", help="Arm remote calls (double gate)")
    p_loop_stdio.add_argument("--allow-network-egress", action="store_true", help="Allow network egress (double gate)")
    p_loop_stdio.add_argument("--approved-by-human", action="store_true", help="Mark HITL as approved")
    p_loop_stdio.add_argument("--replay-mode", action="store_true", help="Forbid any remote calls regardless of gates")
    p_loop_stdio.add_argument(
        "--capabilities",
        default="memory_write",
        help="Comma-separated capability names (THREAD-030); auto-adds llm_remote/net_egress for remote flags",
    )
    p_loop_stdio.add_argument("--workspace-id", default="local", help="Workspace identifier (default: local)")
    p_loop_stdio.add_argument("--data-dir", default="data", help="Output data dir for evidence/trace (default: ./data)")
    p_loop_stdio.add_argument("--idempotency-key", help="Idempotency key (default: derived from trace)")
    p_loop_stdio.add_argument("--deadline-ms", default=60000, type=int, help="Deadline in milliseconds (default: 60000)")
    p_loop_stdio.add_argument(
        "--runtime-mode",
        default="hybrid",
        choices=["direct", "hybrid"],
        help="Assistant runtime mode: direct|hybrid (default: hybrid)",
    )
    p_loop_stdio.add_argument(
        "--no-direct-fallback",
        dest="direct_fallback",
        action="store_false",
        help="Disable direct fallback when hybrid runtime fails",
    )
    p_loop_stdio.set_defaults(direct_fallback=True)
    p_loop_stdio.add_argument("--trace-id")
    p_loop_stdio.add_argument("--max-turns", type=int, help="Stop after N turns (useful for tests)")
    p_loop_stdio.add_argument("--followup-at", default=None, help="FU2: schedule a follow-up run at this UTC ISO time")
    p_loop_stdio.set_defaults(_fn=cmd_mvp_assistant_loop_stdio)

    p_rel = sub_mvp.add_parser(
        "release-pack",
        help="Emit an MVP release evidence pack (admission tests only; emits unittest.txt + manifest.json)",
    )
    p_rel.add_argument(
        "--out-dir",
        help="Output directory for this pack (default: ./data/releases/<release_id> under repo root)",
    )
    p_rel.add_argument("--release-id", help="Release identifier (default: auto-generate)")
    p_rel.set_defaults(_fn=cmd_mvp_release_pack)

    p_rc = sub_mvp.add_parser(
        "rc-pack",
        help="Emit an MVP RC evidence pack (admission + assistant-demo replay + trace + collab refs)",
    )
    p_rc.add_argument(
        "--out-dir",
        help="Output directory for this pack (default: ./data/releases/<release_id> under repo root)",
    )
    p_rc.add_argument("--release-id", help="RC identifier (default: auto-generate)")
    p_rc.add_argument("--data-dir", default="data", help="Data dir for traces (default: ./data)")
    p_rc.add_argument("--demo-query", default="写一封简短邮件申请改期", help="Query for assistant-demo")
    p_rc.add_argument("--backend", default="local_mock", help="local_mock|codex_oauth|doubao_ark|minimax (default: local_mock)")
    p_rc.set_defaults(_fn=cmd_mvp_rc_pack)

    args = parser.parse_args(argv)
    return int(args._fn(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
