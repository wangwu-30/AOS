from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, Optional

from agentos_next.kernel.capabilities import capability_items_for_policy_context
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest, ExecuteResult
from agentos_next.kernel.orchestrator import Orchestrator
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import TraceContext, TraceEvent
from agentos_next.runtime.local_executor import LocalExecutor

StrategyId = Literal["A", "B", "C"]


@dataclass(frozen=True)
class MemorySeedItem:
    item_id: str
    content: str
    tags: tuple[str, ...] = ()
    ttl_seconds: int = 0


@dataclass(frozen=True)
class MemoryEvalLabels:
    relevant_item_ids: tuple[str, ...]
    conflict_item_ids: tuple[str, ...]
    max_reasonable_hits: int = 5
    expect_correction: Optional[bool] = None


@dataclass(frozen=True)
class MemoryEvalCase:
    case_id: str
    seed_memory: tuple[MemorySeedItem, ...]
    query: str
    labels: MemoryEvalLabels
    notes: str = ""
    strategy_hints: dict[str, Any] | None = None


@dataclass(frozen=True)
class StrategyOutput:
    retrieval_trace_ref: str
    results: list[dict[str, Any]]
    used_evidence_refs: list[str]
    retrieval_chain: dict[str, Any]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_id(prefix: str, *parts: str) -> str:
    seed = "|".join(parts).encode("utf-8")
    digest = hashlib.sha256(seed).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _tokens(text: str) -> set[str]:
    return {tok for tok in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", text.lower()) if tok}


def _score_token_overlap(query: str, text: str) -> float:
    q = _tokens(query)
    if not q:
        return 0.0
    t = _tokens(text)
    if not t:
        return 0.0
    return float(len(q.intersection(t))) / float(len(q))


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected list of strings")
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _require_str(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _parse_seed_item(obj: dict[str, Any], *, case_id: str, index: int) -> MemorySeedItem:
    item_id = _require_str(obj.get("item_id"), name=f"{case_id}.seed_memory[{index}].item_id")
    content = _require_str(obj.get("content"), name=f"{case_id}.seed_memory[{index}].content")
    tags = tuple(_as_str_list(obj.get("tags")))
    ttl_seconds = int(obj.get("ttl_seconds") or 0)
    if ttl_seconds < 0:
        raise ValueError(f"{case_id}.seed_memory[{index}].ttl_seconds must be >= 0")
    return MemorySeedItem(item_id=item_id, content=content, tags=tags, ttl_seconds=ttl_seconds)


def _parse_labels(obj: dict[str, Any], *, case_id: str) -> MemoryEvalLabels:
    relevant_item_ids = tuple(_as_str_list(obj.get("relevant_item_ids")))
    conflict_item_ids = tuple(_as_str_list(obj.get("conflict_item_ids")))
    max_reasonable_hits = int(obj.get("max_reasonable_hits") or 5)
    if max_reasonable_hits <= 0:
        raise ValueError(f"{case_id}.labels.max_reasonable_hits must be >= 1")
    expect_raw = obj.get("expect_correction")
    expect_correction: Optional[bool]
    if expect_raw is None:
        expect_correction = None
    elif isinstance(expect_raw, bool):
        expect_correction = expect_raw
    else:
        raise ValueError(f"{case_id}.labels.expect_correction must be bool|null")
    return MemoryEvalLabels(
        relevant_item_ids=relevant_item_ids,
        conflict_item_ids=conflict_item_ids,
        max_reasonable_hits=max_reasonable_hits,
        expect_correction=expect_correction,
    )


def _parse_case(obj: dict[str, Any], *, index: int) -> MemoryEvalCase:
    case_id = _require_str(obj.get("case_id"), name=f"dataset[{index}].case_id")
    query = _require_str(obj.get("query"), name=f"{case_id}.query")
    seed_raw = obj.get("seed_memory")
    labels_raw = obj.get("labels")
    if not isinstance(seed_raw, list) or not seed_raw:
        raise ValueError(f"{case_id}.seed_memory must be a non-empty array")
    if not isinstance(labels_raw, dict):
        raise ValueError(f"{case_id}.labels must be an object")
    seed_memory = tuple(_parse_seed_item(v, case_id=case_id, index=i) for i, v in enumerate(seed_raw) if isinstance(v, dict))
    if not seed_memory:
        raise ValueError(f"{case_id}.seed_memory contains no valid item object")
    labels = _parse_labels(labels_raw, case_id=case_id)
    notes = str(obj.get("notes") or "")
    hints_raw = obj.get("strategy_hints")
    hints = dict(hints_raw) if isinstance(hints_raw, dict) else None
    return MemoryEvalCase(
        case_id=case_id,
        seed_memory=seed_memory,
        query=query,
        labels=labels,
        notes=notes,
        strategy_hints=hints,
    )


def load_memory_eval_dataset(dataset_path: str | Path) -> list[MemoryEvalCase]:
    path = Path(dataset_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    cases: list[MemoryEvalCase] = []
    for idx, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        obj = json.loads(line)
        if not isinstance(obj, dict):
            raise ValueError(f"dataset line {idx + 1} must be a JSON object")
        cases.append(_parse_case(obj, index=idx))
    if not cases:
        raise ValueError("dataset is empty")
    ids = [c.case_id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("dataset case_id must be unique")
    return cases


def _extract_tool_output(res: ExecuteResult, evidence: FileEvidenceStore) -> dict[str, Any]:
    for er in reversed(list(res.evidence_refs)):
        if er.kind != "tool_io":
            continue
        blob = evidence.get_blob(er.ref)
        if blob is None:
            continue
        data = json.loads(blob.content.decode("utf-8"))
        if isinstance(data, dict):
            return data
    raise ValueError("missing tool_io output")


def _search_req(
    *,
    workspace_id: str,
    trace_id: str,
    turn_id: str,
    span_id: str,
    idempotency_key: str,
    query: str,
    limit: int,
) -> ExecuteRequest:
    return ExecuteRequest(
        workspace_id=workspace_id,
        skill_ref="builtin://memory.search",
        input={
            "query": query,
            "intent": "generic",
            "scope": {"workspace_id": workspace_id},
            "kinds": ["profile", "preference", "procedure", "anti_pattern", "delivery_summary", "note"],
            "limit": limit,
            "include_stale": False,
            "include_deleted": False,
        },
        idempotency_key=idempotency_key,
        deadline_ms=5000,
        trace=TraceContext(trace_id=trace_id, turn_id=turn_id, span_id=span_id),
        policy_context={"capabilities": capability_items_for_policy_context(["memory_search"])},
        preferred_target="local",
    )


def _write_req(
    *,
    workspace_id: str,
    trace_id: str,
    turn_id: str,
    span_id: str,
    idempotency_key: str,
    item: MemorySeedItem,
) -> ExecuteRequest:
    return ExecuteRequest(
        workspace_id=workspace_id,
        skill_ref="builtin://memory.write",
        input={
            "record": {
                "kind": "note",
                "summary": item.content[:160],
                "payload": {"statement": item.content},
                "memory_key": item.item_id,
                "scope": {"workspace_id": workspace_id},
                "source": "legacy_import",
                "tags": list(item.tags),
                "ttl_seconds": int(item.ttl_seconds),
            }
        },
        idempotency_key=idempotency_key,
        deadline_ms=5000,
        trace=TraceContext(trace_id=trace_id, turn_id=turn_id, span_id=span_id),
        policy_context={"capabilities": capability_items_for_policy_context(["memory_write"])},
        preferred_target="local",
    )


def _load_trace_has_retrieval_ref(trace_path: Path, retrieval_ref: str) -> bool:
    if not retrieval_ref or not trace_path.exists():
        return False
    for raw in trace_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        event = json.loads(raw)
        if not isinstance(event, dict):
            continue
        if event.get("event_type") != "RETRIEVAL_CHAIN":
            continue
        evs = event.get("evidence_refs")
        if not isinstance(evs, list):
            continue
        for er in evs:
            if isinstance(er, dict) and er.get("ref") == retrieval_ref:
                return True
    return False


def _emit_strategy_chain(
    *,
    evidence: FileEvidenceStore,
    trace: FileTraceLogger,
    trace_ctx: TraceContext,
    strategy: StrategyId,
    query: str,
    selected: list[dict[str, Any]],
    base_retrieval_ref: str,
    extra_debug: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    chain = {
        "schema_version": "1.0.0",
        "type": "retrieval_chain",
        "source": f"eval.memory.strategy_{strategy.lower()}",
        "strategy": strategy,
        "query": query,
        "base_retrieval_trace_ref": base_retrieval_ref,
        "scanned_count": int(extra_debug.get("scanned_count", 0)),
        "filtered": dict(extra_debug.get("filtered", {})),
        "selected": [
            {
                "item_id": str(item.get("item_id") or ""),
                "evidence_ref": str(item.get("evidence_ref") or ""),
                "score": float(item.get("score") or 0.0),
            }
            for item in selected
        ],
    }
    ref = evidence.add_json(chain, kind="routing")
    trace.emit(
        TraceEvent(
            schema_version="1.0.0",
            ctx=trace_ctx,
            event_type="RETRIEVAL_CHAIN",
            ts=_utc_iso(),
            evidence_refs=(ref,),
            data={"strategy": strategy},
        )
    )
    return ref.ref, chain


def _strategy_a(
    *,
    search_output: dict[str, Any],
    retrieval_chain: dict[str, Any],
    item_by_ref: dict[str, MemorySeedItem],
) -> StrategyOutput:
    raw_results = search_output.get("results")
    if not isinstance(raw_results, list):
        raw_results = []
    results: list[dict[str, Any]] = []
    for row in raw_results:
        if not isinstance(row, dict):
            continue
        evidence_ref = str(row.get("evidence_ref") or "")
        item = item_by_ref.get(evidence_ref)
        results.append(
            {
                "item_id": item.item_id if item else "",
                "evidence_ref": evidence_ref,
                "score": float(row.get("score") or 0.0),
                "preview": row.get("preview"),
                "tags": list(item.tags) if item else [],
            }
        )
    used = [str(results[0]["evidence_ref"])] if results else []
    return StrategyOutput(
        retrieval_trace_ref=str(search_output.get("retrieval_trace_ref") or ""),
        results=results,
        used_evidence_refs=used,
        retrieval_chain=retrieval_chain,
    )


def _strategy_b(
    *,
    case: MemoryEvalCase,
    evidence: FileEvidenceStore,
    trace: FileTraceLogger,
    trace_ctx: TraceContext,
    base_output: StrategyOutput,
) -> StrategyOutput:
    hints = case.strategy_hints or {}
    blocked_tags = set(_as_str_list(hints.get("blacklist_tags")))
    focus_tags = set(_as_str_list(hints.get("focus_tags")))
    filtered: list[dict[str, Any]] = []
    for row in base_output.results:
        tags = set(str(t) for t in row.get("tags", []))
        if blocked_tags and tags.intersection(blocked_tags):
            continue
        filtered.append(dict(row))
    rows = filtered if filtered else [dict(x) for x in base_output.results]
    rows.sort(
        key=lambda x: (
            1 if focus_tags.intersection(set(str(t) for t in x.get("tags", []))) else 0,
            float(x.get("score") or 0.0),
            str(x.get("item_id") or ""),
        ),
        reverse=True,
    )
    trace_ref, chain = _emit_strategy_chain(
        evidence=evidence,
        trace=trace,
        trace_ctx=trace_ctx,
        strategy="B",
        query=case.query,
        selected=rows,
        base_retrieval_ref=base_output.retrieval_trace_ref,
        extra_debug={
            "scanned_count": len(base_output.results),
            "filtered": {
                "blocked_by_tag": max(0, len(base_output.results) - len(rows)),
                "blacklist_tags": sorted(blocked_tags),
                "focus_tags": sorted(focus_tags),
            },
        },
    )
    used = [str(rows[0]["evidence_ref"])] if rows else []
    return StrategyOutput(retrieval_trace_ref=trace_ref, results=rows, used_evidence_refs=used, retrieval_chain=chain)


def _strategy_c(
    *,
    case: MemoryEvalCase,
    evidence: FileEvidenceStore,
    trace: FileTraceLogger,
    trace_ctx: TraceContext,
    item_by_ref: dict[str, MemorySeedItem],
    item_ref_by_id: dict[str, str],
    base_output: StrategyOutput,
) -> StrategyOutput:
    base_score = {str(x.get("evidence_ref") or ""): float(x.get("score") or 0.0) for x in base_output.results}
    ranked: list[dict[str, Any]] = []
    for item in case.seed_memory:
        evidence_ref = item_ref_by_id.get(item.item_id, "")
        l0_bonus = 0.2 if "session" in set(item.tags) else 0.0
        l1_bonus = 0.3 if evidence_ref in base_score else 0.0
        l2_score = _score_token_overlap(case.query, item.content)
        combined = float(base_score.get(evidence_ref, 0.0)) + l0_bonus + l1_bonus + l2_score
        if combined <= 0.0:
            continue
        ranked.append(
            {
                "item_id": item.item_id,
                "evidence_ref": evidence_ref,
                "score": combined,
                "preview": item.content[:200],
                "tags": list(item.tags),
                "score_parts": {
                    "base": float(base_score.get(evidence_ref, 0.0)),
                    "l0": l0_bonus,
                    "l1": l1_bonus,
                    "l2": l2_score,
                },
            }
        )
    if not ranked:
        ranked = [dict(x) for x in base_output.results]
    ranked.sort(key=lambda x: (float(x.get("score") or 0.0), str(x.get("item_id") or "")), reverse=True)
    trace_ref, chain = _emit_strategy_chain(
        evidence=evidence,
        trace=trace,
        trace_ctx=trace_ctx,
        strategy="C",
        query=case.query,
        selected=ranked,
        base_retrieval_ref=base_output.retrieval_trace_ref,
        extra_debug={
            "scanned_count": len(item_by_ref),
            "filtered": {"dropped_zero_score": max(0, len(item_by_ref) - len(ranked))},
        },
    )
    used = [str(ranked[0]["evidence_ref"])] if ranked else []
    return StrategyOutput(retrieval_trace_ref=trace_ref, results=ranked, used_evidence_refs=used, retrieval_chain=chain)


def _metric_case(
    *,
    case: MemoryEvalCase,
    strategy_output: StrategyOutput,
    trace_path: Path,
) -> tuple[dict[str, bool], dict[str, Any]]:
    top1 = str(strategy_output.results[0].get("item_id") or "") if strategy_output.results else ""
    relevant_set = set(case.labels.relevant_item_ids)
    conflict_set = set(case.labels.conflict_item_ids)
    retrieved_ids = [str(x.get("item_id") or "") for x in strategy_output.results]
    relevant_at_1 = bool(top1 and top1 in relevant_set)
    conflict = bool((top1 and top1 in conflict_set) or any(item_id in conflict_set for item_id in retrieved_ids))
    selected_refs = {
        str(x.get("evidence_ref") or "")
        for x in strategy_output.retrieval_chain.get("selected", [])
        if isinstance(x, dict) and str(x.get("evidence_ref") or "")
    }
    used_refs = {str(v) for v in strategy_output.used_evidence_refs if str(v)}
    trace_event_found = _load_trace_has_retrieval_ref(trace_path, strategy_output.retrieval_trace_ref)
    context_faithfulness = bool(strategy_output.retrieval_trace_ref) and trace_event_found and used_refs.issubset(selected_refs)
    over_recall = len(retrieved_ids) > int(case.labels.max_reasonable_hits)
    if case.labels.expect_correction is None:
        need_correction = (not relevant_at_1) or conflict
    else:
        need_correction = bool(case.labels.expect_correction)
    metrics = {
        "relevant_at_1": relevant_at_1,
        "conflict": conflict,
        "context_faithfulness": context_faithfulness,
        "over_recall": over_recall,
        "need_correction": need_correction,
    }
    debug = {
        "scanned_count": int(strategy_output.retrieval_chain.get("scanned_count", 0)),
        "filtered": dict(strategy_output.retrieval_chain.get("filtered", {})),
        "selected_scores": [
            {
                "item_id": str(x.get("item_id") or ""),
                "evidence_ref": str(x.get("evidence_ref") or ""),
                "score": float(x.get("score") or 0.0),
            }
            for x in strategy_output.retrieval_chain.get("selected", [])
            if isinstance(x, dict)
        ],
        "trace_event_found": trace_event_found,
    }
    return metrics, debug


async def _evaluate_case(
    *,
    case: MemoryEvalCase,
    strategy: StrategyId,
    index: int,
    seed: int,
) -> dict[str, Any]:
    with TemporaryDirectory(prefix=f"agentos_next_eval_{strategy.lower()}_{index}_") as td:
        data_dir = Path(td)
        workspace_id = "ws_memory_eval"
        trace_id = _stable_id("tr_eval", strategy, str(seed), case.case_id)
        turn_id = _stable_id("turn_eval", strategy, case.case_id)

        orchestrator = Orchestrator.for_data_dir(str(data_dir), local_executor=LocalExecutor.for_data_dir(data_dir))
        evidence = FileEvidenceStore(data_dir=data_dir)
        trace = FileTraceLogger(data_dir=data_dir)

        item_by_ref: dict[str, MemorySeedItem] = {}
        item_ref_by_id: dict[str, str] = {}
        for item_idx, item in enumerate(case.seed_memory):
            req_write = _write_req(
                workspace_id=workspace_id,
                trace_id=trace_id,
                turn_id=turn_id,
                span_id=_stable_id("span_seed", case.case_id, str(item_idx)),
                idempotency_key=_stable_id("idem_seed", case.case_id, item.item_id),
                item=item,
            )
            write_res = await orchestrator.execute(req_write)
            if write_res.status != "accepted":
                raise RuntimeError(f"memory.write failed for {case.case_id}:{item.item_id} -> {write_res.error_code}")
            write_out = _extract_tool_output(write_res, evidence)
            evidence_ref = str(write_out.get("evidence_ref") or "")
            if not evidence_ref.startswith("ev_"):
                raise RuntimeError(f"invalid evidence_ref from memory.write: {evidence_ref}")
            item_by_ref[evidence_ref] = item
            item_ref_by_id[item.item_id] = evidence_ref

        req_search = _search_req(
            workspace_id=workspace_id,
            trace_id=trace_id,
            turn_id=turn_id,
            span_id=_stable_id("span_search", case.case_id),
            idempotency_key=_stable_id("idem_search", strategy, case.case_id),
            query=case.query,
            limit=max(20, int(case.labels.max_reasonable_hits)),
        )
        search_res = await orchestrator.execute(req_search)
        if search_res.status != "accepted":
            raise RuntimeError(f"memory.search failed for {case.case_id} -> {search_res.error_code}")
        search_out = _extract_tool_output(search_res, evidence)
        base_retrieval_ref = str(search_out.get("retrieval_trace_ref") or "")
        base_blob = evidence.get_blob(base_retrieval_ref) if base_retrieval_ref else None
        base_chain = (
            json.loads(base_blob.content.decode("utf-8"))
            if base_blob is not None
            else {
                "schema_version": "1.0.0",
                "type": "retrieval_chain",
                "source": "builtin.memory.search",
                "query": case.query,
                "scanned_count": 0,
                "filtered": {},
                "selected": [],
            }
        )
        base_output = _strategy_a(search_output=search_out, retrieval_chain=base_chain, item_by_ref=item_by_ref)

        trace_ctx = TraceContext(
            trace_id=trace_id,
            turn_id=turn_id,
            span_id=_stable_id("span_strategy", strategy, case.case_id),
        )
        if strategy == "A":
            final_output = base_output
        elif strategy == "B":
            final_output = _strategy_b(
                case=case,
                evidence=evidence,
                trace=trace,
                trace_ctx=trace_ctx,
                base_output=base_output,
            )
        else:
            final_output = _strategy_c(
                case=case,
                evidence=evidence,
                trace=trace,
                trace_ctx=trace_ctx,
                item_by_ref=item_by_ref,
                item_ref_by_id=item_ref_by_id,
                base_output=base_output,
            )

        metrics, debug = _metric_case(
            case=case,
            strategy_output=final_output,
            trace_path=data_dir / "traces" / f"{trace_id}.jsonl",
        )
        top1_item_id = str(final_output.results[0].get("item_id") or "") if final_output.results else ""
        return {
            "case_id": case.case_id,
            "top1_item_id": top1_item_id,
            "retrieved_item_ids": [str(x.get("item_id") or "") for x in final_output.results],
            "retrieval_trace_ref": final_output.retrieval_trace_ref,
            "metrics": metrics,
            "debug": debug,
        }


def _aggregate(case_reports: list[dict[str, Any]]) -> dict[str, float]:
    total = max(1, len(case_reports))
    def _ratio(metric_key: str) -> float:
        count = 0
        for row in case_reports:
            metrics = row.get("metrics")
            if isinstance(metrics, dict) and bool(metrics.get(metric_key)):
                count += 1
        return float(count) / float(total)
    return {
        "relevant_at_1": _ratio("relevant_at_1"),
        "conflict_rate": _ratio("conflict"),
        "context_faithfulness": _ratio("context_faithfulness"),
        "over_recall_rate": _ratio("over_recall"),
        "user_correction_rate": _ratio("need_correction"),
    }


def run_memory_effect_eval(
    *,
    dataset_path: str | Path,
    strategy: StrategyId,
    out_path: str | Path | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    cases = load_memory_eval_dataset(dataset_path)

    async def _run() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for idx, case in enumerate(cases):
            rows.append(await _evaluate_case(case=case, strategy=strategy, index=idx, seed=seed))
        return rows

    case_reports = asyncio.run(_run())
    report = {
        "schema_version": "1.0.0",
        "strategy": strategy,
        "dataset_path": str(Path(dataset_path)),
        "generated_at": _utc_iso(),
        "aggregate": _aggregate(case_reports),
        "per_case": case_reports,
    }
    if out_path is not None:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return report
