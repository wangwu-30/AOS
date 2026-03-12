from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StrategyAggregate:
    strategy: str
    relevant_at_1: float
    conflict_rate: float
    context_faithfulness: float
    over_recall_rate: float
    user_correction_rate: float

    @classmethod
    def from_report(cls, report: dict[str, Any]) -> "StrategyAggregate":
        strategy = str(report.get("strategy") or "").upper()
        agg = report.get("aggregate")
        if not isinstance(agg, dict):
            raise ValueError(f"strategy {strategy or '?'} missing aggregate")
        return cls(
            strategy=strategy,
            relevant_at_1=float(agg.get("relevant_at_1", 0.0)),
            conflict_rate=float(agg.get("conflict_rate", 0.0)),
            context_faithfulness=float(agg.get("context_faithfulness", 0.0)),
            over_recall_rate=float(agg.get("over_recall_rate", 0.0)),
            user_correction_rate=float(agg.get("user_correction_rate", 0.0)),
        )


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    obj = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"report must be object: {p}")
    return obj


def _collect_case_metrics(report: dict[str, Any]) -> dict[str, dict[str, bool]]:
    per_case = report.get("per_case")
    if not isinstance(per_case, list):
        raise ValueError(f"strategy {report.get('strategy')} missing per_case list")
    out: dict[str, dict[str, bool]] = {}
    for row in per_case:
        if not isinstance(row, dict):
            continue
        case_id = str(row.get("case_id") or "").strip()
        metrics = row.get("metrics")
        if not case_id or not isinstance(metrics, dict):
            continue
        out[case_id] = {
            "relevant_at_1": bool(metrics.get("relevant_at_1")),
            "conflict": bool(metrics.get("conflict")),
            "context_faithfulness": bool(metrics.get("context_faithfulness")),
            "over_recall": bool(metrics.get("over_recall")),
            "need_correction": bool(metrics.get("need_correction")),
        }
    if not out:
        raise ValueError(f"strategy {report.get('strategy')} has empty per_case metrics")
    return out


def _validate_report(report: dict[str, Any]) -> str:
    strategy = str(report.get("strategy") or "").upper()
    if strategy not in {"A", "B", "C"}:
        raise ValueError(f"invalid report strategy: {strategy!r}")
    schema_version = str(report.get("schema_version") or "")
    if schema_version != "1.0.0":
        raise ValueError(f"unsupported schema_version: {schema_version!r}")
    _ = StrategyAggregate.from_report(report)
    _ = _collect_case_metrics(report)
    return strategy


def _strategy_rank_key(agg: StrategyAggregate, *, eligible: bool) -> tuple[float, ...]:
    return (
        1.0 if eligible else 0.0,
        -agg.user_correction_rate,
        agg.relevant_at_1,
        -agg.over_recall_rate,
        -agg.conflict_rate,
        agg.context_faithfulness,
    )


def _regressions_vs_baseline(
    baseline_cases: dict[str, dict[str, bool]],
    candidate_cases: dict[str, dict[str, bool]],
    *,
    strategy: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case_id, base in sorted(baseline_cases.items()):
        cand = candidate_cases.get(case_id)
        if cand is None:
            rows.append({"case_id": case_id, "strategy": strategy, "regressions": ["missing_case"]})
            continue
        regressions: list[str] = []
        if base["relevant_at_1"] and not cand["relevant_at_1"]:
            regressions.append("relevant_at_1_down")
        if (not base["conflict"]) and cand["conflict"]:
            regressions.append("conflict_up")
        if base["context_faithfulness"] and not cand["context_faithfulness"]:
            regressions.append("faithfulness_down")
        if (not base["over_recall"]) and cand["over_recall"]:
            regressions.append("over_recall_up")
        if (not base["need_correction"]) and cand["need_correction"]:
            regressions.append("correction_up")
        if regressions:
            rows.append({"case_id": case_id, "strategy": strategy, "regressions": regressions})
    return rows


def compare_memory_effect_reports(
    *,
    report_a_path: str | Path,
    report_b_path: str | Path,
    report_c_path: str | Path,
    baseline_strategy: str = "A",
    guard_epsilon: float = 0.0,
    out_path: str | Path | None = None,
) -> dict[str, Any]:
    reports_raw = {
        "A": _load_json(report_a_path),
        "B": _load_json(report_b_path),
        "C": _load_json(report_c_path),
    }

    strategies_found: set[str] = set()
    reports_by_strategy: dict[str, dict[str, Any]] = {}
    for _, raw in reports_raw.items():
        strategy = _validate_report(raw)
        if strategy in strategies_found:
            raise ValueError(f"duplicate strategy report: {strategy}")
        strategies_found.add(strategy)
        reports_by_strategy[strategy] = raw
    if strategies_found != {"A", "B", "C"}:
        raise ValueError(f"require A/B/C reports, got: {sorted(strategies_found)}")

    base_key = str(baseline_strategy).upper()
    if base_key not in {"A", "B", "C"}:
        raise ValueError("baseline_strategy must be A|B|C")
    baseline_report = reports_by_strategy[base_key]
    baseline_agg = StrategyAggregate.from_report(baseline_report)
    baseline_cases = _collect_case_metrics(baseline_report)

    case_id_sets = {k: set(_collect_case_metrics(v).keys()) for k, v in reports_by_strategy.items()}
    if case_id_sets["A"] != case_id_sets["B"] or case_id_sets["A"] != case_id_sets["C"]:
        raise ValueError("A/B/C per_case case_id set mismatch")

    rankings: list[dict[str, Any]] = []
    guard_violations: list[dict[str, Any]] = []
    per_case_regressions: list[dict[str, Any]] = []
    deltas_vs_baseline: dict[str, dict[str, float]] = {}

    for strategy in ("A", "B", "C"):
        report = reports_by_strategy[strategy]
        agg = StrategyAggregate.from_report(report)
        candidate_cases = _collect_case_metrics(report)
        deltas = {
            "delta_relevant_at_1": agg.relevant_at_1 - baseline_agg.relevant_at_1,
            "delta_conflict_rate": agg.conflict_rate - baseline_agg.conflict_rate,
            "delta_context_faithfulness": agg.context_faithfulness - baseline_agg.context_faithfulness,
            "delta_over_recall_rate": agg.over_recall_rate - baseline_agg.over_recall_rate,
            "delta_user_correction_rate": agg.user_correction_rate - baseline_agg.user_correction_rate,
        }
        deltas_vs_baseline[strategy] = deltas

        violations: list[str] = []
        if strategy != base_key:
            if agg.conflict_rate > baseline_agg.conflict_rate + guard_epsilon:
                violations.append("conflict_rate_increase")
            if agg.context_faithfulness + guard_epsilon < baseline_agg.context_faithfulness:
                violations.append("context_faithfulness_drop")
            per_case_regressions.extend(
                _regressions_vs_baseline(baseline_cases, candidate_cases, strategy=strategy)
            )
        eligible = len(violations) == 0
        rank_key = _strategy_rank_key(agg, eligible=eligible)
        rankings.append(
            {
                "strategy": strategy,
                "eligible": eligible,
                "rank_key": list(rank_key),
                "aggregate": {
                    "relevant_at_1": agg.relevant_at_1,
                    "conflict_rate": agg.conflict_rate,
                    "context_faithfulness": agg.context_faithfulness,
                    "over_recall_rate": agg.over_recall_rate,
                    "user_correction_rate": agg.user_correction_rate,
                },
                "deltas_vs_baseline": deltas,
            }
        )
        if violations:
            guard_violations.append({"strategy": strategy, "violations": violations})

    rankings.sort(key=lambda row: tuple(float(x) for x in row["rank_key"]), reverse=True)

    winner: str | None = None
    for row in rankings:
        if row["eligible"]:
            winner = str(row["strategy"])
            break
    if winner is None:
        winner = base_key

    result = {
        "schema_version": "1.0.0",
        "generated_at": _utc_iso(),
        "baseline_strategy": base_key,
        "reports": {
            "A": str(Path(report_a_path)),
            "B": str(Path(report_b_path)),
            "C": str(Path(report_c_path)),
        },
        "winner_strategy": winner,
        "ranking": rankings,
        "guard_violations": guard_violations,
        "deltas_vs_baseline": deltas_vs_baseline,
        "per_case_regressions": sorted(per_case_regressions, key=lambda x: (x["strategy"], x["case_id"])),
        "decision_gate": {
            "main_metric": "user_correction_rate",
            "guardrails": ["conflict_rate_not_increase", "context_faithfulness_not_drop"],
        },
    }

    if out_path is not None:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    return result
