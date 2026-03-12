from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Optional

from agentos_next.kernel.evidence_manifest import ManifestWriteRequest, verify_turn_manifest, write_turn_manifest_once
from agentos_next.kernel.evidence_store import FileEvidenceStore
from agentos_next.kernel.executor import ExecuteRequest
from agentos_next.kernel.policy_engine import evaluate_execute_policy
from agentos_next.kernel.trace_logger import FileTraceLogger
from agentos_next.kernel.types import EvidenceRef, TraceContext, TraceEvent


SCHEMA_VERSION = "1.0.0"


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    k = (len(xs) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    if f == c:
        return float(xs[f])
    d0 = xs[f] * (c - k)
    d1 = xs[c] * (k - f)
    return float(d0 + d1)


def _make_evidence_batch(*, data_dir: Path, count: int) -> list[EvidenceRef]:
    ev = FileEvidenceStore(data_dir=data_dir)
    out: list[EvidenceRef] = []
    for i in range(int(count)):
        out.append(
            ev.add_json(
                {"schema_version": "1.0.0", "type": "bench", "i": i},
                kind="snapshot",
            )
        )
    return out


def _ensure_trace_turn_line(*, data_dir: Path, trace: TraceContext) -> None:
    tl = FileTraceLogger(data_dir=data_dir)
    tl.emit(
        TraceEvent(
            schema_version="1.0.0",
            ctx=trace,
            event_type="POLICY_DECIDED",
            ts="2026-02-26T00:00:00Z",
            evidence_refs=(),
            data={"decision": "allow", "reason_code": "allow", "error_code": None, "action_fingerprint": "", "count": 1, "threshold": 2},
        )
    )


def _bench_sign(*, count: int) -> tuple[bool, dict[str, Any]]:
    with TemporaryDirectory(prefix="agentos_next_perf_sign_") as td:
        data_dir = Path(td) / "data"
        trace = TraceContext(trace_id="tr_perf", turn_id="turn_perf", span_id="span_perf")
        _ensure_trace_turn_line(data_dir=data_dir, trace=trace)
        evidence_refs = _make_evidence_batch(data_dir=data_dir, count=count)

        req = ManifestWriteRequest(
            data_dir=data_dir,
            trace=trace,
            workspace_id="ws_perf",
            operator_ref="builtin://bench",
            idempotency_key="idem_perf",
            execute_status="accepted",
            execute_error_code=None,
            evidence_refs=tuple(evidence_refs),
            replay_mode=False,
        )

        t0 = _now_ms()
        res = write_turn_manifest_once(req=req)
        dt = _now_ms() - t0

        ok = bool(res.ok)
        detail = {
            "ok": ok,
            "elapsed_ms": dt,
            "error_code": res.error_code,
            "reason_code": res.reason_code,
        }
        return ok, detail


def _bench_verify(*, count: int) -> tuple[bool, dict[str, Any]]:
    with TemporaryDirectory(prefix="agentos_next_perf_verify_") as td:
        data_dir = Path(td) / "data"
        trace = TraceContext(trace_id="tr_perf", turn_id="turn_perf", span_id="span_perf")
        _ensure_trace_turn_line(data_dir=data_dir, trace=trace)
        evidence_refs = _make_evidence_batch(data_dir=data_dir, count=count)
        wreq = ManifestWriteRequest(
            data_dir=data_dir,
            trace=trace,
            workspace_id="ws_perf",
            operator_ref="builtin://bench",
            idempotency_key="idem_perf",
            execute_status="accepted",
            execute_error_code=None,
            evidence_refs=tuple(evidence_refs),
            replay_mode=False,
        )
        wres = write_turn_manifest_once(req=wreq)
        if not wres.ok:
            return False, {"ok": False, "error_code": wres.error_code, "reason_code": wres.reason_code}

        t0 = _now_ms()
        ok, code, errors = verify_turn_manifest(data_dir=data_dir, trace_id=trace.trace_id, turn_id=trace.turn_id)
        dt = _now_ms() - t0
        return bool(ok), {"ok": bool(ok), "elapsed_ms": dt, "error_code": (code or None), "errors": list(errors)}


def _bench_budget(*, count: int) -> tuple[bool, dict[str, Any]]:
    # THREAD-029: budget v1 allow-check (remote_llm_calls). This measures the overhead of
    # the policy evaluation loop under a representative remote LLM intent.
    with TemporaryDirectory(prefix="agentos_next_perf_budget_") as td:
        data_dir = Path(td) / "data"
        trace = TraceContext(trace_id="tr_perf", turn_id="turn_perf", span_id="span_perf")
        req = ExecuteRequest(
            workspace_id="ws_perf",
            operator_ref="builtin://bench",
            arguments={"q": "hi"},
            idempotency_key="idem_perf",
            deadline_ms=1000,
            trace=trace,
            policy_context={
                "verify_asvp": False,
                "backend": "codex_oauth",
                "remote_calls_armed": True,
                "allow_network_egress": True,
                # THREAD-030 capabilities: must satisfy required net_egress + llm_remote.
                "capabilities": [{"name": "net_egress", "scope": "workspace"}, {"name": "llm_remote", "scope": "workspace"}],
            },
            preferred_target="local",
            budget_slice=1,
        )

        samples: list[float] = []
        for _ in range(int(count)):
            t0 = _now_ms()
            _ = evaluate_execute_policy(req=req, data_dir=data_dir)
            samples.append(_now_ms() - t0)

        threshold_ms = 2.0
        mean = statistics.mean(samples) if samples else 0.0
        out = {
            "ok": mean <= threshold_ms,
            "count": int(count),
            "elapsed_ms_total": float(sum(samples)),
            "per_call_ms": {
                "mean": mean,
                "p50": _percentile(samples, 50),
                "p95": _percentile(samples, 95),
                "p99": _percentile(samples, 99),
                "max": max(samples) if samples else 0.0,
            },
            "threshold_ms": threshold_ms,
            "note": "budget v1 allow-check overhead under remote LLM intent (backend=codex_oauth)",
        }
        return bool(out["ok"]), out


def run(argv: Optional[list[str]] = None) -> tuple[int, dict[str, Any]]:
    ap = argparse.ArgumentParser(prog="perf_bench", add_help=True)
    ap.add_argument("--op", required=True, choices=["sign", "verify", "budget"], help="Benchmark operation")
    ap.add_argument("--count", type=int, default=1000, help="Count (events for sign/verify; iterations for budget)")
    args = ap.parse_args(argv)

    op = str(args.op)
    count = int(args.count)
    if count <= 0:
        out = {"schema_version": SCHEMA_VERSION, "ok": False, "error_code": "E_INPUT_SCHEMA", "message": "count must be > 0"}
        return 3, out

    # Run 3 trials to support the "连续 3 次均值达标" acceptance rule.
    trials: list[dict[str, Any]] = []
    ok_all = True
    for _ in range(3):
        if op == "sign":
            ok, detail = _bench_sign(count=count)
        elif op == "verify":
            ok, detail = _bench_verify(count=count)
        else:
            ok, detail = _bench_budget(count=count)
        ok_all = ok_all and bool(ok)
        trials.append(detail)

    # Summarize elapsed_ms where available.
    elapsed = [float(t.get("elapsed_ms", 0.0)) for t in trials if isinstance(t, dict)]
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ok": ok_all,
        "op": op,
        "count": count,
        "trials": trials,
        "summary": {
            "elapsed_ms_mean": statistics.mean(elapsed) if elapsed else 0.0,
            "elapsed_ms_p95": _percentile(elapsed, 95) if elapsed else 0.0,
        },
    }
    return (0 if ok_all else 2), out


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
