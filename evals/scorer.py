"""Scoring + the telemetry gate (design doc 4.4, 4.10).

Two responsibilities:
  1. Adjudicate task success via the task's programmatic assertion (the gate).
  2. Compare paired baseline-vs-candidate telemetry and flag regressions.

POC note: the POC runs a SINGLE build, so paired-gating is exercised by comparing
two sample sets (e.g. baseline=candidate as a self-test, or two refs later). The
median + threshold logic is real; wiring the second build is the next step.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .harness import RunResult
from .task import Task, TelemetryThresholds


@dataclass
class SampleStats:
    """Aggregate of K runs of one build on one task."""

    success_rate: float
    median_cost_usd: float
    median_tool_calls: float
    median_turns: float
    n: int


def aggregate(results: list[RunResult]) -> SampleStats:
    if not results:
        return SampleStats(0.0, 0.0, 0.0, 0.0, 0)
    return SampleStats(
        success_rate=sum(r.success for r in results) / len(results),
        median_cost_usd=statistics.median(r.total_cost_usd for r in results),
        median_tool_calls=statistics.median(r.tool_call_count for r in results),
        median_turns=statistics.median(float(r.num_turns) for r in results),
        n=len(results),
    )


def adjudicate_ctx(task: Task, result: RunResult, ctx: dict) -> tuple[bool, str]:
    """Run the task's programmatic assertion (ctx-aware) against a single run.

    Note: we do NOT short-circuit on result.success here. Some tasks (e.g.
    troubleshoot) can succeed even if the agent's own run had quirks, and the
    assertion itself inspects the real outcome (job status, diagnosis text).
    """
    if result.subtype == "no_result_event":
        return False, "agent run produced no result (CLI died)"
    return task.assertion(result, ctx)


@dataclass
class GateOutcome:
    passed: bool
    reasons: list[str]


def _pct_regression(baseline: float, candidate: float) -> float:
    """Percent by which candidate exceeds baseline. Negative = improvement."""
    if baseline == 0:
        return 0.0 if candidate == 0 else float("inf")
    return (candidate - baseline) / baseline * 100.0


def paired_gate(
    baseline: SampleStats,
    candidate: SampleStats,
    thresholds: TelemetryThresholds,
) -> GateOutcome:
    """Gate on the PAIRED delta (design doc 4.4) -- never vs a stored history.

    Fails if candidate regresses success OR exceeds a telemetry threshold.
    """
    reasons: list[str] = []

    if candidate.success_rate < baseline.success_rate:
        reasons.append(
            f"success regressed: {baseline.success_rate:.0%} -> {candidate.success_rate:.0%}"
        )

    cost_reg = _pct_regression(baseline.median_cost_usd, candidate.median_cost_usd)
    if cost_reg > thresholds.max_cost_regression_pct:
        reasons.append(
            f"cost +{cost_reg:.0f}% (>{thresholds.max_cost_regression_pct:.0f}%): "
            f"${baseline.median_cost_usd:.4f} -> ${candidate.median_cost_usd:.4f}"
        )

    tool_reg = _pct_regression(baseline.median_tool_calls, candidate.median_tool_calls)
    if tool_reg > thresholds.max_tool_call_regression_pct:
        reasons.append(
            f"tool-calls +{tool_reg:.0f}% (>{thresholds.max_tool_call_regression_pct:.0f}%): "
            f"{baseline.median_tool_calls:g} -> {candidate.median_tool_calls:g}"
        )

    turn_reg = _pct_regression(baseline.median_turns, candidate.median_turns)
    if turn_reg > thresholds.max_turn_regression_pct:
        reasons.append(
            f"turns +{turn_reg:.0f}% (>{thresholds.max_turn_regression_pct:.0f}%): "
            f"{baseline.median_turns:g} -> {candidate.median_turns:g}"
        )

    return GateOutcome(passed=not reasons, reasons=reasons)
