from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class GoldenTraceThresholds:
    """Quantitative thresholds for GT2 gate."""

    max_flake_rate: float = 0.01
    min_consecutive_passes: int = 10
    rollback_on_consecutive_failures: int = 2


@dataclass(frozen=True)
class GoldenTraceGateReport:
    total_runs: int
    failures: int
    flake_rate: float
    max_consecutive_passes: int
    max_consecutive_failures: int
    passed: bool
    rollback_required: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "total_runs": self.total_runs,
            "failures": self.failures,
            "flake_rate": self.flake_rate,
            "max_consecutive_passes": self.max_consecutive_passes,
            "max_consecutive_failures": self.max_consecutive_failures,
            "passed": self.passed,
            "rollback_required": self.rollback_required,
        }


def evaluate_golden_trace_gate(
    run_passes: Sequence[bool],
    *,
    thresholds: GoldenTraceThresholds = GoldenTraceThresholds(),
) -> GoldenTraceGateReport:
    total = len(run_passes)
    failures = sum(1 for ok in run_passes if not ok)
    flake_rate = (float(failures) / float(total)) if total > 0 else 1.0

    max_pass_streak = 0
    max_fail_streak = 0
    pass_streak = 0
    fail_streak = 0
    for ok in run_passes:
        if ok:
            pass_streak += 1
            fail_streak = 0
        else:
            fail_streak += 1
            pass_streak = 0
        if pass_streak > max_pass_streak:
            max_pass_streak = pass_streak
        if fail_streak > max_fail_streak:
            max_fail_streak = fail_streak

    rollback_required = max_fail_streak >= int(thresholds.rollback_on_consecutive_failures)
    passed = (
        total >= int(thresholds.min_consecutive_passes)
        and max_pass_streak >= int(thresholds.min_consecutive_passes)
        and flake_rate <= float(thresholds.max_flake_rate)
        and not rollback_required
    )

    return GoldenTraceGateReport(
        total_runs=total,
        failures=failures,
        flake_rate=flake_rate,
        max_consecutive_passes=max_pass_streak,
        max_consecutive_failures=max_fail_streak,
        passed=passed,
        rollback_required=rollback_required,
    )
