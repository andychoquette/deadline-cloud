"""Generate CLI docstring-improvement recommendations from run telemetry.

The thesis (design doc, revised): comparing baseline vs revised docstrings tells
us whether better help improves agent performance, and WHERE. This module turns
the observed runs into concrete, reviewable recommendations.

POC scope: heuristic + evidence-based. It (1) reports the measured baseline->revised
delta as the headline evidence, and (2) inspects which `deadline ... --help` calls
the agent made and how much it floundered (turns, repeated help lookups, failures)
to point at the commands whose docstrings most need work. A future version can hand
the struggling transcripts to an LLM to draft specific docstring rewrites.
"""

from __future__ import annotations

import re


def _help_commands(records) -> list[str]:
    """Extract `deadline ... --help` invocations from the agent's bash tool calls."""
    seen: list[str] = []
    for rec in records:
        for ev in rec.result.raw_events:
            if ev.get("type") != "assistant":
                continue
            for blk in ev.get("message", {}).get("content", []):
                if blk.get("type") == "tool_use" and blk.get("name") == "Bash":
                    cmd = blk.get("input", {}).get("command", "")
                    for m in re.findall(r"deadline[\w\s-]*?--help", cmd):
                        norm = m.strip()
                        if norm not in seen:
                            seen.append(norm)
    return seen


def suggest(task_id: str, per_variant: dict, stats: dict) -> dict:
    recs: list[str] = []
    evidence: dict = {}

    candidate = next((v for v in stats if v != "baseline"), None)
    if "baseline" in stats and candidate is not None:
        b, r = stats["baseline"], stats[candidate]
        evidence["success_delta"] = r.success_rate - b.success_rate
        evidence["turn_delta"] = r.median_turns - b.median_turns
        evidence["tool_delta"] = r.median_tool_calls - b.median_tool_calls
        evidence["cost_delta_usd"] = r.median_cost_usd - b.median_cost_usd

        if r.success_rate > b.success_rate:
            recs.append(
                f"Revised docstrings RAISED success {b.success_rate:.0%}->{r.success_rate:.0%}. "
                "Adopt the revised help; it measurably helped the agent complete the task."
            )
        if r.median_turns < b.median_turns:
            recs.append(
                f"Revised docstrings cut median turns {b.median_turns:g}->{r.median_turns:g} "
                "-- the agent needed less back-and-forth to understand the CLI."
            )
        if r.median_tool_calls < b.median_tool_calls:
            recs.append(
                f"Revised docstrings cut median tool-calls {b.median_tool_calls:g}->"
                f"{r.median_tool_calls:g} (fewer exploratory commands)."
            )
        if r.success_rate <= b.success_rate and r.median_turns >= b.median_turns:
            recs.append(
                "Revised docstrings did NOT improve performance on this task -- "
                "the current revisions may not address the agent's actual confusion. "
                "Inspect the transcripts below for where it floundered."
            )

    # Evidence: which help commands the agent reached for, per variant.
    for variant, records in per_variant.items():
        helps = _help_commands(records)
        if helps:
            evidence.setdefault("help_lookups", {})[variant] = helps
            recs.append(
                f"[{variant}] agent consulted help for: {', '.join(helps)} -- "
                "these command docstrings are on the agent's critical path; prioritize them."
            )

    # Tasks where the agent failed: flag the command docstrings as candidates.
    for variant, records in per_variant.items():
        fails = [r for r in records if not r.passed]
        if fails:
            recs.append(
                f"[{variant}] {len(fails)}/{len(records)} runs failed: "
                f"\"{fails[0].detail}\" -- the docstrings for the commands this task "
                "exercises likely need clearer guidance (format, required args, lifecycle)."
            )

    if not recs:
        recs.append("No actionable signal yet -- increase K or add more tasks.")

    return {"items": recs, "evidence": evidence}
