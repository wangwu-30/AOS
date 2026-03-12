from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentos_next.apps.assistant_loop import AssistantLoopRequest, AssistantLoopResult
from agentos_next.apps.assistant_runtime import run_assistant_runtime_async
from agentos_next.kernel.types import TraceContext


@dataclass(frozen=True)
class ScenarioSpec:
    name: str
    expected_error_code: str | None
    expect_followup_task: bool = False


SCENARIOS: tuple[ScenarioSpec, ...] = (
    ScenarioSpec(name="HITL_BLOCK", expected_error_code="E_HITL_REQUIRED"),
    ScenarioSpec(name="REPLAY_BLOCK", expected_error_code="E_REPLAY_REMOTE_DISABLED"),
    ScenarioSpec(name="SCHED_FOLLOWUP_SUCCESS", expected_error_code=None, expect_followup_task=True),
    ScenarioSpec(name="TOOL_FAIL", expected_error_code="E_EXECUTION_FAILED"),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _make_high_risk_skill_copy(*, dst_dir: Path) -> Path:
    root = _repo_root()
    src = root / "examples" / "skills" / "personal_assistant_brief"
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    shutil.copytree(src, dst_dir)
    contract_path = dst_dir / "contract.skill"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["risk_level"] = "high"
    contract_path.write_text(json.dumps(contract, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dst_dir


def build_request_for_scenario(
    *,
    scenario: str,
    data_dir: Path,
    trace_id: str,
    turn_id: str,
    span_id: str,
) -> AssistantLoopRequest:
    root = _repo_root()
    trace = TraceContext(trace_id=trace_id, turn_id=turn_id, span_id=span_id)

    common = dict(
        query="帮我处理一条简短提醒",
        workspace_id="ws_hy2_gt2",
        data_dir=str(data_dir),
        trace=trace,
        idempotency_key=f"idem_{scenario.lower()}_{trace_id}",
        deadline_ms=6000,
        verify_asvp=True,
        public_keys_dir=(root / "examples" / "keys"),
        backend="local_mock",
        planner="deterministic",
        model=None,
        remote_calls_armed=False,
        allow_network_egress=False,
        approved_by_human=False,
        replay_mode=False,
        followup_at=None,
    )

    if scenario == "HITL_BLOCK":
        high_skill = _make_high_risk_skill_copy(dst_dir=data_dir / "skill_hitl_high")
        common["assistant_skill_dir"] = high_skill
        common["verify_asvp"] = False
    elif scenario == "REPLAY_BLOCK":
        common["backend"] = "codex_oauth"
        common["remote_calls_armed"] = True
        common["allow_network_egress"] = True
        common["replay_mode"] = True
        common["query"] = "给我一个简短回复"
    elif scenario == "SCHED_FOLLOWUP_SUCCESS":
        common["followup_at"] = "2026-02-25T09:00:01Z"
        common["query"] = "帮我写一个简短跟进"
        common["verify_asvp"] = False
    elif scenario == "TOOL_FAIL":
        common["assistant_skill_dir"] = data_dir / "missing_skill"
        common["verify_asvp"] = False
        common["query"] = "输出一个简短结果"
    else:
        raise ValueError(f"unknown scenario: {scenario}")

    return AssistantLoopRequest(**common)  # type: ignore[arg-type]


async def run_scenario(
    *,
    scenario: str,
    runtime_mode: str,
    data_dir: Path,
    trace_id: str,
) -> AssistantLoopResult:
    req = build_request_for_scenario(
        scenario=scenario,
        data_dir=data_dir,
        trace_id=trace_id,
        turn_id=f"turn_{scenario.lower()}",
        span_id=f"span_{scenario.lower()}",
    )
    return await run_assistant_runtime_async(
        req,
        runtime_mode=("hybrid" if str(runtime_mode).lower() == "hybrid" else "direct"),
        direct_fallback=True,
    )


def canonical_result_view(res: AssistantLoopResult) -> dict[str, Any]:
    step_view = []
    for idx, st in enumerate(res.steps, start=1):
        step_view.append(
            {
                "i": idx,
                "status": st.get("status"),
                "error_code": st.get("error_code"),
                "target": st.get("target"),
                "evidence_ref_count": len(st.get("evidence_refs", [])) if isinstance(st.get("evidence_refs"), list) else 0,
            }
        )
    final_output_keys: list[str] | None = None
    if isinstance(res.final_output, dict):
        final_output_keys = sorted(str(k) for k in res.final_output.keys())
    return {
        "ok": bool(res.ok),
        "error_code": res.error_code,
        "steps": step_view,
        "final_output_keys": final_output_keys,
        "followup_task_present": bool(res.followup_task_id),
        "followup_plan_ref_present": bool(res.followup_plan_ref),
        "top_evidence_ref_count": len(res.evidence_refs),
    }


def collect_traceable_refs(res: AssistantLoopResult) -> set[str]:
    refs: set[str] = set()
    refs.update(str(r) for r in res.evidence_refs)
    for st in res.steps:
        evs = st.get("evidence_refs")
        if isinstance(evs, list):
            refs.update(str(x) for x in evs if isinstance(x, str))
    return refs


def assert_refs_traceable(*, data_dir: Path, refs: set[str]) -> None:
    for ref in refs:
        meta = data_dir / "evidence" / "meta" / f"{ref}.json"
        blob = data_dir / "evidence" / "blobs" / ref
        if not meta.exists() or not blob.exists():
            raise AssertionError(f"non-traceable evidence ref: {ref}")


def canonical_trace_shape(trace_path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not trace_path.exists():
        return out
    for raw in trace_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        ev = json.loads(line)
        ctx = ev.get("ctx")
        data = ev.get("data")
        refs = ev.get("evidence_refs")
        out.append(
            {
                "event_type": ev.get("event_type"),
                "ctx_keys": sorted(ctx.keys()) if isinstance(ctx, dict) else [],
                "data_keys": sorted(data.keys()) if isinstance(data, dict) else [],
                "evidence_ref_count": len(refs) if isinstance(refs, list) else 0,
            }
        )
    return out
