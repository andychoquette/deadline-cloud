"""Task definition -- the core artifact (design doc 4.3).

A task pairs a prompt with the environment it needs and a machine-checkable
success predicate. For the POC, tasks are OFFLINE (no AWS): `setup` populates a
sandbox dir with fixture files, and `assertion` inspects that dir / the RunResult
after the agent runs.

Real-AWS tasks (ephemeral farm, run-id-tagged assertions) slot in behind the
same shape once the credential model is settled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# Lifecycle callbacks. `ctx` is a per-run dict the hooks/assertion share
# (e.g. prepare() submits a failing job and stashes its job_id for the assertion).
# Imported lazily as a type hint only to avoid a circular import.
AssertionFn = Callable[["object", dict], "tuple[bool, str]"]
SetupFn = Callable[[Path, dict], None]
PrepareFn = Callable[[dict], None]      # runs BEFORE the agent (e.g. submit failing job)
FinalizeFn = Callable[["object", dict], None]  # runs AFTER the agent (e.g. submit+wait)


@dataclass
class TelemetryThresholds:
    """Per-task regression bounds for the telemetry gate (design doc 4.4).

    Used for the paired baseline-vs-candidate delta, not absolute limits.
    """

    max_cost_regression_pct: float = 30.0
    max_tool_call_regression_pct: float = 30.0
    max_turn_regression_pct: float = 30.0


@dataclass
class Task:
    id: str
    prompt: str
    allowed_tools: list[str]
    setup: SetupFn                       # populate the sandbox dir (workdir, ctx)
    assertion: AssertionFn               # machine-checkable success predicate (result, ctx)
    prepare: PrepareFn | None = None     # optional pre-agent hook (ctx) -- e.g. submit failing job
    finalize: FinalizeFn | None = None   # optional post-agent hook (result, ctx) -- e.g. submit+wait
    mcp_config: Path | None = None
    max_turns: int = 15
    requires_aws: bool = False           # gate: skip/flag if real AWS not authenticated
    uses_mock: bool = False              # inject AwsInABox endpoint env into the agent run
    model: str | None = None             # full Bedrock profile id; None = wrapper default
    thresholds: TelemetryThresholds = field(default_factory=TelemetryThresholds)
