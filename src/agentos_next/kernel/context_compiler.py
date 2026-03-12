import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional, Sequence

from agentos_next.kernel.evidence_store import EvidenceBlob, FileEvidenceStore
from agentos_next.kernel.memory_store import FileMemoryStore, L1Record
from agentos_next.kernel.types import EvidenceRef, TraceContext

# -----------------------------------------------------------------------------
# Frozen Error Codes & Violations
# -----------------------------------------------------------------------------

ContextErrorCode = Literal[
    "E_CTX_SCHEMA_INVALID",
    "E_CTX_BUDGET_EXCEEDED",
    "E_CTX_POLICY_VIOLATION",
    "E_CTX_REPLAY_DENY",
]

ViolationCode = Literal[
    "identity_mutation_attempt",
    "cross_workspace_leakage",
    "budget_trim_overflow",
    "append_only_violation",
]

ViolationSeverity = Literal["critical", "warning"]

@dataclass(frozen=True)
class ContextViolation:
    code: ViolationCode
    severity: ViolationSeverity
    detail: str

# -----------------------------------------------------------------------------
# Input Types
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class CompileContextKeys:
    trace_id: str
    turn_id: str
    workspace_id: str
    replay_mode: bool = False

@dataclass(frozen=True)
class CompileRefs:
    meta_identity_ref: str = ""
    meta_operator_catalog_ref: str = ""
    c0_identity_ref: str = ""
    c1_capability_index_ref: str = ""

    @property
    def resolved_meta_identity_ref(self) -> str:
        return str(self.meta_identity_ref or self.c0_identity_ref or "").strip()

    @property
    def resolved_meta_operator_catalog_ref(self) -> str:
        return str(self.meta_operator_catalog_ref or self.c1_capability_index_ref or "").strip()

@dataclass(frozen=True)
class MemoryQuery:
    tags: tuple[str, ...] = ()
    query: Optional[str] = None
    limit: int = 5
    freshness_window_seconds: Optional[int] = None
    include_stale_fallback: bool = True
    include_tombstoned_fallback: bool = False

@dataclass(frozen=True)
class RuntimeSnapshot:
    budget_remaining: Optional[int] = None
    approvals_pending: Optional[int] = None
    last_error_code: Optional[str] = None
    task_state_digest: Optional[str] = None
    pending_contract: Optional[dict[str, Any]] = None
    expected_next_user_act: Optional[str] = None
    active_project_id: Optional[str] = None
    last_clarification_question: Optional[str] = None
    blocker: Optional[dict[str, Any]] = None
    last_delivery_state: Optional[str] = None
    last_delivery_summary: Optional[str] = None
    interaction_mode_preference: Optional[str] = None

@dataclass(frozen=True)
class TaskIntent:
    user_message: str
    actions_hint: tuple[str, ...] = ()

@dataclass(frozen=True)
class ContextBudgets:
    max_bytes_total: int
    per_layer_caps: dict[str, int] = field(default_factory=dict)

@dataclass(frozen=True)
class CompileRequest:
    ctx: CompileContextKeys
    refs: CompileRefs
    c2_memory_query: MemoryQuery
    c3_runtime_snapshot: RuntimeSnapshot
    task_intent: TaskIntent
    budgets: ContextBudgets
    policy_context_passthrough: dict[str, Any] = field(default_factory=dict)

# -----------------------------------------------------------------------------
# Output Types
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class UsageBytes:
    c0: int
    c1: int
    c2: int
    c3: int
    task_intent: int
    total: int

@dataclass(frozen=True)
class GoldilocksStatus:
    usage_ratio: float
    status: Literal["under", "optimal", "over"]

@dataclass(frozen=True)
class CompiledContext:
    c4_text: str
    usage_bytes: UsageBytes
    goldilocks: GoldilocksStatus
    selected_refs: dict[str, str]

@dataclass(frozen=True)
class SelectionTrace:
    decision_log: tuple[str, ...]
    violations: tuple[ContextViolation, ...]

@dataclass(frozen=True)
class CompileResult:
    ok: bool
    error_code: Optional[ContextErrorCode]
    compiled: Optional[CompiledContext]
    selection_trace: Optional[SelectionTrace]
    evidence_refs: tuple[EvidenceRef, ...] = ()

# -----------------------------------------------------------------------------
# Core Compiler
# -----------------------------------------------------------------------------

class _ReadOnlyEvidenceLoader:
    def __init__(self, data_dir: Path):
        self._meta_dir = data_dir / "evidence" / "meta"
        self._blobs_dir = data_dir / "evidence" / "blobs"

    def get_blob(self, ref: str) -> Optional[EvidenceBlob]:
        meta_path = self._meta_dir / f"{ref}.json"
        blob_path = self._blobs_dir / ref
        if not meta_path.exists() or not blob_path.exists():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        content = blob_path.read_bytes()
        return EvidenceBlob(
            ref=str(meta.get("ref", ref)),
            kind=str(meta["kind"]),  # type: ignore[arg-type]
            ts=str(meta["ts"]),
            content_type=str(meta["content_type"]),
            content=content,
        )

class _ReadOnlyMemoryLoader:
    def __init__(self, data_dir: Path):
        self._l1_dir = data_dir / "memory" / "l1"

    def iter_l1(self) -> list[L1Record]:
        if not self._l1_dir.exists():
            return []
        out = []
        for p in sorted(self._l1_dir.glob("ev_*.json")):
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            out.append(L1Record(
                schema_version=str(obj.get("schema_version", "1.0.0")),
                evidence_ref=str(obj.get("evidence_ref", "")),
                created_at=str(obj.get("created_at", "")),
                tags=tuple(str(t) for t in (obj.get("tags") or []) if isinstance(t, (str, int, float))),
                ttl_seconds=int(obj.get("ttl_seconds") or 0),
                expires_at=str(obj.get("expires_at")) if obj.get("expires_at") is not None else None,
                tombstoned=bool(obj.get("tombstoned", False)),
                tombstoned_at=str(obj.get("tombstoned_at")) if obj.get("tombstoned_at") is not None else None,
            ))
        return out


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def _evaluate_goldilocks(usage: int, max_bytes: int) -> GoldilocksStatus:
    if max_bytes <= 0:
        return GoldilocksStatus(1.0, "over")
    ratio = usage / max_bytes
    if ratio < 0.40:
        status = "under"
    elif ratio <= 0.70:
        status = "optimal"
    else:
        status = "over"
    return GoldilocksStatus(ratio, status)


def _normalize_retrieval_text(raw: Any) -> str:
    text = " ".join(str(raw or "").lower().split())
    text = re.sub(r"[^0-9a-z_\u4e00-\u9fff]+", " ", text)
    return " ".join(text.split())


def _extract_retrieval_query_terms(query_norm: str) -> tuple[str, ...]:
    if not query_norm:
        return ()
    terms: set[str] = set(re.findall(r"[a-z0-9_]{2,}", query_norm))
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", query_norm):
        terms.add(chunk)
        if len(chunk) > 4:
            terms.add(chunk[:4])
            terms.add(chunk[-4:])
    return tuple(sorted(terms, key=len, reverse=True))


def _score_retrieval_text(*, query_norm: str, query_terms: tuple[str, ...], text_norm: str) -> int:
    score = 0
    if query_norm and query_norm in text_norm:
        score += 64
    for term in query_terms:
        if term in text_norm:
            score += min(len(term), 12)
    return score


def _safe_parse_utc_iso(value: Any) -> datetime:
    s = str(value or "").strip()
    if not s:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _is_stale_record(*, rec: L1Record, now: datetime, freshness_window_seconds: Optional[int]) -> bool:
    if rec.is_expired(now=now):
        return True
    window = int(freshness_window_seconds or 0)
    if window <= 0:
        return False
    created_at = _safe_parse_utc_iso(rec.created_at)
    return created_at < (now - timedelta(seconds=window))


def _rank_candidates_for_query(
    candidates: list[tuple[int, datetime, L1Record, str]],
    *,
    decision_log: list[str],
    tier_name: str,
) -> list[tuple[int, datetime, L1Record, str]]:
    matched_candidates = [it for it in candidates if it[0] > 0]
    if matched_candidates:
        decision_log.append(f"C2 {tier_name} retrieval ranked by query relevance (hits={len(matched_candidates)})")
        return sorted(matched_candidates, key=lambda it: (it[0], it[1]), reverse=True)
    decision_log.append(f"C2 {tier_name} retrieval fallback to recency order (no relevance hits)")
    return sorted(candidates, key=lambda it: it[1], reverse=True)

def compile_step_context(*, req: CompileRequest, data_dir: Path) -> CompileResult:
    if req.ctx.replay_mode:
        if not (data_dir / "evidence").exists() or not (data_dir / "memory").exists():
            return CompileResult(
                ok=False,
                error_code="E_CTX_REPLAY_DENY",
                compiled=None,
                selection_trace=None
            )
        evidence_store: Any = _ReadOnlyEvidenceLoader(data_dir)
        memory_store: Any = _ReadOnlyMemoryLoader(data_dir)
    else:
        evidence_store = FileEvidenceStore(data_dir)
        memory_store = FileMemoryStore(data_dir)
    
    violations: list[ContextViolation] = []
    decision_log: list[str] = []
    selected_refs: dict[str, str] = {}
    
    # 1. Load Meta.Identity (legacy alias: C0) - PINNED, NEVER TRIMMED
    meta_identity_ref = req.refs.resolved_meta_identity_ref
    c0_blob = evidence_store.get_blob(meta_identity_ref)
    if not c0_blob:
        # FALLBACK: Use default PA identity if explicit ref is missing
        c0_text = "Standard AgentOS Personal Assistant (autonomous state machine mode)."
        decision_log.append(f"Meta.Identity ref {meta_identity_ref} not found, using default identity")
    else:
        c0_text = c0_blob.content.decode("utf-8", errors="replace")
        selected_refs["c0"] = meta_identity_ref
        selected_refs["meta_identity"] = meta_identity_ref
    
    # Check T1: Identity mutation attempt
    if req.policy_context_passthrough.get("mutate_identity"):
        violations.append(ContextViolation("identity_mutation_attempt", "critical", "Attempt to mutate C0 rejected"))
        return CompileResult(ok=False, error_code="E_CTX_POLICY_VIOLATION", compiled=None, selection_trace=None)

    # Check T7: Append-only violation
    if req.policy_context_passthrough.get("squash_history"):
        violations.append(ContextViolation("append_only_violation", "warning", "Squash or prune operation requested"))
        decision_log.append("History squash applied via passthrough")

    # 2. Load Meta.Operator Catalog Seed (legacy alias: C1 Capability Index)
    meta_operator_catalog_ref = req.refs.resolved_meta_operator_catalog_ref
    c1_blob = evidence_store.get_blob(meta_operator_catalog_ref)
    if c1_blob:
        import json as _json
        try:
            cap_index = _json.loads(c1_blob.content.decode("utf-8", errors="replace"))
            c1_lines: list[str] = []
            operators = cap_index.get("operators")
            skills = cap_index.get("skills")
            caps = cap_index.get("capabilities")
            if isinstance(operators, list) and operators:
                c1_lines = ["Operator Search Seed:"]
                for item in operators[:16]:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or item.get("operator") or "unknown").strip() or "unknown"
                    desc = str(item.get("description") or item.get("summary") or "").strip()
                    c1_lines.append(f"- {name}: {desc}".rstrip(": "))
            elif isinstance(skills, list) and skills:
                c1_lines = ["Skill Search Seed:"]
                for item in skills[:16]:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or item.get("skill") or "unknown").strip() or "unknown"
                    desc = str(item.get("description") or item.get("summary") or "").strip()
                    c1_lines.append(f"- {name}: {desc}".rstrip(": "))
            elif isinstance(caps, list) and caps:
                c1_lines = ["Operator Policy Seed:"]
                for c in caps[:16]:
                    if not isinstance(c, dict):
                        continue
                    name = str(c.get("name") or "unknown").strip() or "unknown"
                    desc = str(c.get("description") or "").strip()
                    c1_lines.append(f"- {name}: {desc}".rstrip(": "))
            if c1_lines:
                c1_text = "\n".join(c1_lines)
            else:
                c1_text = "No specific operator catalog declared."
        except Exception:
            c1_text = c1_blob.content.decode("utf-8", errors="replace")
        selected_refs["c1"] = meta_operator_catalog_ref
        selected_refs["meta_operator_catalog"] = meta_operator_catalog_ref
    else:
        # FALLBACK: Provide basic operator policy seed if ref is missing.
        c1_text = "Operator policy is granted dynamically by runtime configuration."
        decision_log.append(
            f"Meta.OperatorCatalog ref {meta_operator_catalog_ref} not found, using generic operator seed"
        )


    # 3. Load C2 (Memory Index) & Check T3 (Cross Workspace Leak)
    l1_records = memory_store.iter_l1()
    t3_leaked = False
    matched: dict[str, Any] = {}  # evidence_ref -> L1Record

    required_tags = tuple(str(tag).strip() for tag in req.c2_memory_query.tags if str(tag).strip())
    for rec in l1_records:
        if rec.evidence_ref in matched:
            continue
        if required_tags and not set(required_tags).issubset(set(rec.tags)):
            continue
        # T3 Security Check: Cross-workspace isolation
        if f"ws_{req.ctx.workspace_id}" not in rec.tags and req.ctx.workspace_id not in rec.tags:
            violations.append(ContextViolation("cross_workspace_leakage", "critical", f"Ref {rec.evidence_ref} belongs to another workspace"))
            t3_leaked = True
            break
        matched[rec.evidence_ref] = rec

    if t3_leaked:
        return CompileResult(ok=False, error_code="E_CTX_POLICY_VIOLATION", compiled=None, selection_trace=None)

    # 4. Assemble Components except C2
    snap = req.c3_runtime_snapshot
    snapshot_lines = ["System State:"]
    if snap.budget_remaining is not None:
        snapshot_lines.append(f"- Budget remaining: {snap.budget_remaining}")
    if snap.approvals_pending is not None:
        snapshot_lines.append(f"- Pending approvals: {snap.approvals_pending}")
    if snap.last_error_code:
        snapshot_lines.append(f"- Last error: {snap.last_error_code}")
    if snap.task_state_digest:
        snapshot_lines.append(f"- Task state: {snap.task_state_digest}")
    if snap.active_project_id:
        snapshot_lines.append(f"- Active project: {snap.active_project_id}")
    if snap.expected_next_user_act:
        snapshot_lines.append(f"- Expected next user act: {snap.expected_next_user_act}")
    if snap.last_delivery_state:
        snapshot_lines.append(f"- Last delivery state: {snap.last_delivery_state}")
    if snap.last_delivery_summary:
        snapshot_lines.append(f"- Last delivery summary: {snap.last_delivery_summary}")
    if isinstance(snap.pending_contract, dict):
        objective = str(snap.pending_contract.get("objective") or "").strip()
        if objective:
            snapshot_lines.append(f"- Pending contract: {objective}")
    if snap.last_clarification_question:
        snapshot_lines.append(f"- Last clarification: {snap.last_clarification_question}")
    if isinstance(snap.blocker, dict):
        reason = str(snap.blocker.get("reason") or snap.blocker.get("summary") or "").strip()
        if reason:
            snapshot_lines.append(f"- Blocker: {reason}")
    
    if len(snapshot_lines) == 1:
        c3_text = "System State: Optimal (no pending issues)"
    else:
        c3_text = "\n".join(snapshot_lines)
    
    intent_parts: list[str] = [req.task_intent.user_message]
    if req.task_intent.actions_hint:
        intent_parts.append("Hints: " + ", ".join(req.task_intent.actions_hint))
    intent_text: str = "\n".join(intent_parts)

    c0_bytes = len(c0_text.encode("utf-8"))
    c1_bytes = len(c1_text.encode("utf-8"))
    c3_bytes = len(c3_text.encode("utf-8"))
    intent_bytes = len(intent_text.encode("utf-8"))
    
    # Static overhead for formatting strings
    assembly_overhead = len(
        "# Meta Identity\n\n# Meta Operator Seed\n\n# L2 Retrieved Memory\n\n# L0 Snapshot\n\n# Task Intent\n\n".encode(
            "utf-8"
        )
    )
    
    available_bytes = req.budgets.max_bytes_total - (c0_bytes + c1_bytes + c3_bytes + intent_bytes + assembly_overhead)
    
    # 5. Fill C2 (Memory) sliding window
    # Ranking strategy: relevance to query first, recency fallback.
    query_raw = req.c2_memory_query.query if req.c2_memory_query.query is not None else req.task_intent.user_message
    query_norm = _normalize_retrieval_text(query_raw)
    query_terms = _extract_retrieval_query_terms(query_norm)

    now = datetime.now(timezone.utc)
    active_candidates: list[tuple[int, datetime, L1Record, str]] = []
    stale_candidates: list[tuple[int, datetime, L1Record, str]] = []
    tombstoned_candidates: list[tuple[int, datetime, L1Record, str]] = []
    for rec in matched.values():
        mem_blob = evidence_store.get_blob(rec.evidence_ref)
        if mem_blob is None:
            continue
        try:
            import json as _json
            mem_data = _json.loads(mem_blob.content.decode("utf-8", errors="replace"))
            mem_content = mem_data.get("content", "") if isinstance(mem_data, dict) else ""
        except Exception:
            mem_content = mem_blob.content.decode("utf-8", errors="replace")
        if not mem_content:
            continue
        entry_text = str(mem_content)
        text_norm = _normalize_retrieval_text(entry_text)
        score = _score_retrieval_text(
            query_norm=query_norm,
            query_terms=query_terms,
            text_norm=text_norm,
        )
        candidate = (score, _safe_parse_utc_iso(rec.created_at), rec, entry_text)
        if rec.tombstoned:
            tombstoned_candidates.append(candidate)
        elif _is_stale_record(
            rec=rec,
            now=now,
            freshness_window_seconds=req.c2_memory_query.freshness_window_seconds,
        ):
            stale_candidates.append(candidate)
        else:
            active_candidates.append(candidate)

    selected_c2_parts: list[str] = []
    c2_selection_count = 0
    c2_accumulated_bytes = 0
    current_selected_refs = dict(selected_refs)
    ordered_tiers: list[tuple[str, list[tuple[int, datetime, L1Record, str]], str | None]] = [
        ("active", active_candidates, None),
    ]
    if req.c2_memory_query.include_stale_fallback:
        ordered_tiers.append(("stale", stale_candidates, "[stale memory - verify freshness] "))
    if req.c2_memory_query.include_tombstoned_fallback:
        ordered_tiers.append(("tombstoned", tombstoned_candidates, "[soft-deleted memory fallback - verify before use] "))

    decision_log.append(
        "C2 retrieval tiers="
        + ",".join(
            [
                f"active:{len(active_candidates)}",
                f"stale:{len(stale_candidates)}",
                f"tombstoned:{len(tombstoned_candidates)}",
            ]
        )
    )

    for tier_name, tier_candidates, prefix in ordered_tiers:
        if c2_selection_count >= int(req.c2_memory_query.limit):
            break
        if not tier_candidates:
            continue
        if tier_name != "active":
            decision_log.append(f"C2 fallback activated: tier={tier_name} because primary context was insufficient")
        ordered = _rank_candidates_for_query(tier_candidates, decision_log=decision_log, tier_name=tier_name)
        for _score, _created_at, rec, entry_text in ordered:
            if c2_selection_count >= int(req.c2_memory_query.limit):
                break
            rendered_entry = f"{prefix}{entry_text}" if prefix else entry_text
            entry_bytes = len(rendered_entry.encode("utf-8")) + 1  # +1 for newline
            if c2_accumulated_bytes + entry_bytes <= max(0, available_bytes):
                selected_c2_parts.append(rendered_entry)
                c2_accumulated_bytes += entry_bytes
                current_selected_refs[f"c2_{c2_selection_count}"] = rec.evidence_ref
                current_selected_refs[f"l2_{c2_selection_count}"] = rec.evidence_ref
                c2_selection_count += 1
            else:
                violations.append(ContextViolation("budget_trim_overflow", "warning", f"Memory trimmed: {rec.evidence_ref} exceeded budget"))
                decision_log.append(f"Trimming L1 memory at {rec.evidence_ref} due to budget")
                break

    # Final assembly of C2 text (restore chronological order)
    selected_c2_parts.reverse()
    c2_text = "\n".join(selected_c2_parts)
    c2_bytes = len(c2_text.encode("utf-8")) if c2_text else 0
    
    total = c0_bytes + c1_bytes + c2_bytes + c3_bytes + intent_bytes
    selected_refs = current_selected_refs
    
    if total > req.budgets.max_bytes_total:
        # This shouldn't happen if available_bytes calculation was correct,
        # but as a fail-safe:
        return CompileResult(
            ok=False,
            error_code="E_CTX_BUDGET_EXCEEDED",
            compiled=None,
            selection_trace=None
        )

    # 6. Assemble Final C4 Context (content-only, for LLM Consumption)
    c4_parts = [
        f"# Meta Identity\n{c0_text}",
        f"# Meta Operator Seed\n{c1_text}",
        f"# L2 Retrieved Memory\n{c2_text if c2_text else '(No previous retrieved memory)'}",
        f"# L0 Snapshot\n{c3_text}",
        f"# Task Intent\n{intent_text}",
    ]
    c4_text = "\n\n".join(c4_parts)
    
    usage = UsageBytes(c0_bytes, c1_bytes, c2_bytes, c3_bytes, intent_bytes, total)
    goldilocks = _evaluate_goldilocks(total, req.budgets.max_bytes_total)
    
    compiled = CompiledContext(c4_text, usage, goldilocks, selected_refs)
    sel_trace = SelectionTrace(tuple(decision_log), tuple(violations))
    
    # 8. Selection Trace Evidence & Replay
    if req.ctx.replay_mode:
        # Zero write in replay
        return CompileResult(
            ok=True,
            error_code=None,
            compiled=compiled,
            selection_trace=sel_trace,
            evidence_refs=()
        )
    else:
        # Write selection trace to evidence
        blob_content = _canonical_json({
            "decision_log": sel_trace.decision_log,
            "violations": [{"code": v.code, "severity": v.severity, "detail": v.detail} for v in sel_trace.violations],
            "selected_refs": compiled.selected_refs
        })
        ev_ref = evidence_store.add_json(
            {"selection_trace": blob_content},
            kind="context_routing"
        )
        return CompileResult(
            ok=True,
            error_code=None,
            compiled=compiled,
            selection_trace=sel_trace,
            evidence_refs=(ev_ref,)
        )
