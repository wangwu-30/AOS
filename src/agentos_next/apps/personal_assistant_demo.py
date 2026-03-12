from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from agentos_next.apps.assistant_loop import AssistantLoopRequest, AssistantLoopResult
from agentos_next.apps.assistant_runtime import run_assistant_runtime_async
from agentos_next.apps.canonical_task_ingress import build_canonical_task_ingress_request
from agentos_next.kernel.types import TraceContext


def _repo_root() -> Path:
    # src/agentos_next/apps/personal_assistant_demo.py -> repo root is 3 levels up.
    # Keep this deterministic so `python -m agentos_next.cli ...` works from any CWD.
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class PersonalAssistantDemoRequest:
    query: str
    skill_dir: Optional[Path] = None
    verify_asvp: bool = True
    public_keys_dir: Optional[Path] = None

    workspace_id: str = "local"
    data_dir: str | Path = "data"
    trace: Optional[TraceContext] = None

    backend: str = "local_mock"  # local_mock | codex_oauth | doubao_ark | minimax
    model_id_override: Optional[str] = None
    intent_backend: Optional[str] = None
    intent_model: Optional[str] = None
    communicator_backend: Optional[str] = None
    communicator_model: Optional[str] = None
    response_language: Optional[str] = None
    remote_calls_armed: bool = False
    allow_network_egress: bool = False
    approved_by_human: bool = False
    replay_mode: bool = False


def run_personal_assistant_demo(req: PersonalAssistantDemoRequest) -> AssistantLoopResult:
    root = _repo_root()
    skill_dir = req.skill_dir or (root / "examples" / "skills" / "personal_assistant_brief")
    keys_dir = req.public_keys_dir or (root / "examples" / "keys")

    if req.trace is None:
        raise ValueError("trace is required (TraceContext)")

    loop_req = AssistantLoopRequest(
        query=str(req.query),
        assistant_skill_dir=skill_dir,
        workspace_id=str(req.workspace_id),
        data_dir=req.data_dir,
        trace=req.trace,
        deadline_ms=60000,
        verify_asvp=bool(req.verify_asvp),
        public_keys_dir=keys_dir,
        backend=str(req.backend),
        planner="model_owned",
        planner_backend=None,
        model=req.model_id_override,
        intent_backend=req.intent_backend,
        intent_model=req.intent_model,
        communicator_backend=req.communicator_backend,
        communicator_model=req.communicator_model,
        response_language=req.response_language,
        remote_calls_armed=bool(req.remote_calls_armed),
        allow_network_egress=bool(req.allow_network_egress),
        approved_by_human=bool(req.approved_by_human),
        replay_mode=bool(req.replay_mode),
    )
    ingress = build_canonical_task_ingress_request(
        loop_req,
        submitter="cli.mvp.assistant-demo",
        consumer="cli.stdout.json",
        raw_input=str(req.query),
        metadata={"command": "mvp assistant-demo"},
    )
    return asyncio.run(run_assistant_runtime_async(ingress, runtime_mode="direct", direct_fallback=True))
