"""Harness: drive Claude Code headless and capture telemetry.

POC scope: invokes the local `claude` CLI in print mode with stream-json output,
which carries BOTH per-tool-call events and a final result event with token/cost
telemetry. No OTLP collector needed -- the JSON stream is the telemetry source.

This is the `HarnessAdapter` seam from the design doc, kept as a plain module
(not a polymorphic interface) until a second harness (Codex/Kiro) is real.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RunResult:
    """One headless agent run: outcome + telemetry, plus the raw event log."""

    success: bool                       # did the CLI complete without error
    subtype: str | None                 # result subtype, e.g. "success" / "error_max_turns"
    tool_calls: list[str] = field(default_factory=list)
    num_turns: int = 0
    total_cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    session_id: str | None = None
    model: str = ""                     # model id reported in modelUsage (what actually ran)
    final_text: str = ""                # the agent's final response text
    workdir: Path | None = None         # the sandbox the agent ran in (for assertions)
    raw_events: list[dict] = field(default_factory=list)

    @property
    def tool_call_count(self) -> int:
        return len(self.tool_calls)

    def telemetry_dict(self) -> dict:
        """Serializable telemetry (excludes the bulky raw event log)."""
        return {
            "success": self.success,
            "subtype": self.subtype,
            "tool_calls": self.tool_calls,
            "tool_call_count": self.tool_call_count,
            "num_turns": self.num_turns,
            "total_cost_usd": self.total_cost_usd,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_ms": self.duration_ms,
            "session_id": self.session_id,
            "model": self.model,
            "final_text": self.final_text,
        }


def run_claude_code(
    prompt: str,
    workdir: Path,
    allowed_tools: list[str],
    *,
    mcp_config: Path | None = None,
    max_turns: int = 15,
    claude_bin: str = "claude",
    env_overrides: dict[str, str] | None = None,
    model: str | None = None,
) -> RunResult:
    """Run Claude Code headless in `workdir`, restricted to `allowed_tools`.

    Tool availability is defined BY INCLUSION (design doc 4.3): only the tools
    listed are auto-approved; bypassPermissions keeps it non-interactive for CI.

    `env_overrides` are added to the subprocess environment -- used to inject the
    docstring variant (PYTHONPATH + DEADLINE_EVALS_HELP) the agent's CLI sees.
    """
    cmd = [
        claude_bin,
        "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",                     # required for stream-json event detail
        "--permission-mode", "bypassPermissions",
        "--max-turns", str(max_turns),
    ]
    if allowed_tools:
        cmd += ["--allowedTools", *allowed_tools]
    if mcp_config is not None:
        cmd += ["--mcp-config", str(mcp_config), "--strict-mcp-config"]
    if model:  # full Bedrock inference-profile id, e.g. global.anthropic.claude-sonnet-4-6[1m]
        cmd += ["--model", model]

    run_env = None
    if env_overrides:
        import os

        run_env = {**os.environ, **env_overrides}

    proc = subprocess.run(
        cmd,
        cwd=str(workdir),
        capture_output=True,
        text=True,
        env=run_env,
    )

    events: list[dict] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # non-JSON lines (rare) are ignored

    return _parse_events(events, proc.returncode, workdir)


def _parse_events(events: list[dict], returncode: int, workdir: Path) -> RunResult:
    tool_calls: list[str] = []
    final: dict | None = None

    for ev in events:
        if ev.get("type") == "assistant":
            for blk in ev.get("message", {}).get("content", []):
                if blk.get("type") == "tool_use":
                    tool_calls.append(blk["name"])
        elif ev.get("type") == "result":
            final = ev

    if final is None:
        # CLI died before emitting a result event.
        return RunResult(
            success=False,
            subtype="no_result_event",
            tool_calls=tool_calls,
            workdir=workdir,
            raw_events=events,
        )

    usage = final.get("usage", {})
    model_used = next(iter(final.get("modelUsage", {})), "")
    return RunResult(
        success=(not final.get("is_error", False)) and returncode == 0,
        subtype=final.get("subtype"),
        tool_calls=tool_calls,
        num_turns=final.get("num_turns", 0),
        total_cost_usd=final.get("total_cost_usd", 0.0),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        duration_ms=final.get("duration_ms", 0),
        session_id=final.get("session_id"),
        model=model_used,
        final_text=final.get("result", "") if isinstance(final.get("result"), str) else "",
        workdir=workdir,
        raw_events=events,
    )
