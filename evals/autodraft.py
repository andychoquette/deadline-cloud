"""Auto-draft improved CLI docstrings from a baseline run where the agent struggled.

Pipeline (design doc, revised -- the "close the loop" feature):
  1. Take a completed baseline run's artifacts (events + which `deadline ... --help`
     the agent consulted, and how much it floundered).
  2. Capture the CURRENT help text for those commands (live `--help` output).
  3. Ask Claude to draft improved, agent-friendlier help -- returned as STRUCTURED
     JSON ({command_path: {help, options}}), never generated code (no exec).
  4. Write autodrafted.json, which the A/B runner can test as the `autodrafted`
     variant (DEADLINE_EVALS_REVISIONS_FILE) against baseline.

This module only PRODUCES the revisions file. Testing it and emitting a patch are
done by the runner + patchgen, kept decoupled.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


def help_commands_from_events(events_path: Path) -> list[str]:
    """Which `deadline ... --help` invocations the agent made, in order."""
    seen: list[str] = []
    for line in events_path.read_text().splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
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


def current_help(command_path: str) -> str:
    """Capture the CLI's current stock help for a command path (e.g. 'bundle submit')."""
    proc = subprocess.run(
        ["deadline", *command_path.split(), "--help"],
        capture_output=True,
        text=True,
    )
    return proc.stdout


def transcript_text(events_path: Path) -> str:
    """A compact transcript of assistant text + bash commands, for the drafting prompt."""
    parts: list[str] = []
    for line in events_path.read_text().splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            for blk in ev.get("message", {}).get("content", []):
                if blk.get("type") == "text":
                    parts.append("ASSISTANT: " + blk["text"][:500])
                elif blk.get("type") == "tool_use":
                    inp = blk.get("input", {})
                    detail = inp.get("command") or inp.get("file_path") or json.dumps(inp)[:200]
                    parts.append(f"TOOL[{blk.get('name')}]: {str(detail)[:300]}")
    return "\n".join(parts[:60])


_DRAFT_PROMPT = """\
You are improving the `--help` text of the AWS Deadline Cloud `deadline` CLI so that
an AI coding agent can drive it more efficiently (fewer exploratory commands, fewer
turns). Below is a transcript of an agent that struggled with the CURRENT help, and
the current help text for the commands it consulted.

Draft improved help. Make it concrete and explicit: state required arguments and
their nature (e.g. that a job bundle is a DIRECTORY containing template.yaml), give a
short copy-pasteable example, and mention the next step in the workflow. Keep it
accurate to the actual CLI behavior shown -- do NOT invent flags.

Return ONLY a JSON object, no prose, in EXACTLY this shape:
{{
  "autodrafted": {{
    "<command path e.g. bundle submit>": {{
      "help": "<revised command help>",
      "options": {{ "<option_name>": "<revised option help>" }}
    }}
  }}
}}

=== AGENT TRANSCRIPT (struggled) ===
{transcript}

=== CURRENT HELP ===
{help_blocks}
"""


class DraftError(RuntimeError):
    """Raised when the drafting step fails to produce any usable revisions."""


def draft(run_dir: Path, out_path: Path, *, claude_bin: str = "claude", attempts: int = 2) -> dict:
    """Generate autodrafted.json from a baseline run-1 artifact directory.

    Raises DraftError if the drafting LLM call fails or yields zero revisions after
    retries -- we must NOT silently degrade to an empty draft, because an empty draft
    makes the 'autodrafted' variant identical to baseline and any measured delta then
    reflects model variance, not docstring changes.
    """
    events_path = run_dir / "events.jsonl"
    help_cmds = help_commands_from_events(events_path)
    paths = []
    for h in help_cmds:
        p = h.replace("deadline", "").replace("--help", "").strip()
        if p and p not in paths:
            paths.append(p)
    if not paths:
        paths = ["bundle submit"]  # sensible default for the authoring task

    help_blocks = "\n\n".join(f"## deadline {p} --help\n{current_help(p)}" for p in paths)
    prompt = _DRAFT_PROMPT.format(
        transcript=transcript_text(events_path), help_blocks=help_blocks
    )

    last_err = ""
    for attempt in range(1, attempts + 1):
        try:
            proc = subprocess.run(
                [claude_bin, "-p", prompt, "--output-format", "json",
                 "--permission-mode", "bypassPermissions", "--max-turns", "1", "--allowedTools", ""],
                capture_output=True, text=True,
            )
        except OSError as e:
            last_err = f"could not launch {claude_bin}: {e}"
            continue
        if proc.returncode != 0:
            last_err = f"claude exited {proc.returncode}: {proc.stderr.strip()[:200]}"
            continue
        try:
            raw = json.loads(proc.stdout)
        except json.JSONDecodeError:
            last_err = "claude stdout was not JSON"
            continue
        text = raw.get("result", "") if isinstance(raw.get("result"), str) else ""
        try:
            drafted = _extract_json(text)
        except (json.JSONDecodeError, ValueError):
            last_err = "could not extract JSON revisions from model reply"
            continue
        if drafted.get("autodrafted"):
            out_path.write_text(json.dumps(drafted, indent=2))
            return drafted
        last_err = "model returned zero revisions"

    raise DraftError(f"drafting failed after {attempts} attempts: {last_err}")


def _extract_json(text: str) -> dict:
    """Pull the JSON object out of the model's reply (handles ```json fences)."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return {"autodrafted": {}}
    return json.loads(text[start : end + 1])
