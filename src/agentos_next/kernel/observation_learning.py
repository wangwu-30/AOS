from __future__ import annotations

from typing import Any


def build_observation_learning_candidates_v1(
    *,
    workspace_id: str,
    task_id: str,
    objective: str,
    delivery_state: str,
    error_code: str | None,
    research_evidence_pack_ref: str | None = None,
    hypothesis_ref: str | None = None,
) -> list[dict[str, Any]]:
    refs = [str(ref).strip() for ref in (research_evidence_pack_ref, hypothesis_ref) if str(ref or "").strip()]
    base = {
        "schema_version": "1.0.0",
        "type": "observation_learning_candidate_v1",
        "workspace_id": str(workspace_id or "").strip(),
        "task_id": str(task_id or "").strip(),
        "objective": str(objective or "").strip(),
        "promotion_policy": "manual_review_required",
        "source_refs": refs,
    }
    candidates: list[dict[str, Any]] = []
    if research_evidence_pack_ref:
        candidates.append(
            {
                **base,
                "candidate_kind": "search_research_strategy_candidate",
                "summary": "review whether the observed search -> browse -> cite path should become a reusable doctrine or SOP",
            }
        )
    if error_code:
        candidates.append(
            {
                **base,
                "candidate_kind": "anti_pattern_candidate",
                "summary": f"review failure path and blockers before hardening a new guardrail ({error_code})",
            }
        )
    elif str(delivery_state or "").strip() == "done":
        candidates.append(
            {
                **base,
                "candidate_kind": "sop_candidate",
                "summary": "review whether this successful execution path should be promoted into a reusable SOP",
            }
        )
    return candidates
