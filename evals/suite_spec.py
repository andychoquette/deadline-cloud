"""Load an eval suite from a JSON file into a list of Task objects.

A suite file is an array of test-case entries. Each entry is one of:

  (A) An INLINE declarative test (offline / mock / read-only), e.g.:
      {
        "id": "list-farms",
        "prompt": "List the deadline farms and report the count.",
        "tools": ["Bash"],
        "env": "mock",                  # "none" | "real_aws" | "mock"
        "model": "opus",                # alias or full id; or "models": [...] to sweep
        "setup_files": {"input.txt": "hello"},   # files written into the sandbox
        "assert": {"final_text_contains": ["farm"]}   # declarative assertion vocab
      }

  (B) A REFERENCE to an existing coded task/suite (keeps Python assertions):
      { "ref": "author_and_submit", "model": "sonnet", "k": 3 }
      { "ref_suite": "cli_read", "models": ["opus", "sonnet"] }

`model`/`models` use short aliases resolved via MODEL_ALIASES, or a full
`global.anthropic...[1m]` id. A `models` array expands the entry into one Task per
model (id suffixed with the model alias) so the report can compare across models.
"""

from __future__ import annotations

import json
from pathlib import Path

from .task import Task, TelemetryThresholds

# Short alias -> full Bedrock inference-profile id (verified working via Cecelia).
MODEL_ALIASES = {
    "opus": "global.anthropic.claude-opus-4-8[1m]",
    "opus-4.8": "global.anthropic.claude-opus-4-8[1m]",
    "opus-4.7": "global.anthropic.claude-opus-4-7[1m]",
    "opus-4.6": "global.anthropic.claude-opus-4-6-v1[1m]",
    "sonnet": "global.anthropic.claude-sonnet-4-6[1m]",
    "sonnet-4.6": "global.anthropic.claude-sonnet-4-6[1m]",
    "haiku": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
}


def resolve_model(name: str | None) -> str | None:
    if not name:
        return None
    return MODEL_ALIASES.get(name, name)  # pass through full ids unchanged


def _short_model(name: str | None) -> str:
    """A short label for a model, for task-id suffixing."""
    if not name:
        return "default"
    for alias, full in MODEL_ALIASES.items():
        if name in (alias, full) and "." in alias:  # prefer the versioned alias
            return alias
    return name.split(".")[-1].replace("[1m]", "").strip("-")[:16] or "model"


def _declarative_assertion(spec: dict):
    """Build an assertion fn from a small declarative vocabulary."""
    contains = spec.get("final_text_contains", [])
    not_contains = spec.get("final_text_not_contains", [])
    file_exists = spec.get("sandbox_file_exists")

    def assertion(result, ctx):  # noqa: ANN001
        text = (result.final_text or "").lower()
        for needle in contains:
            if str(needle).lower() not in text:
                return False, f"answer missing expected text: {needle!r}"
        for needle in not_contains:
            if str(needle).lower() in text:
                return False, f"answer contained forbidden text: {needle!r}"
        if file_exists and result.workdir:
            hits = list(Path(result.workdir).rglob(file_exists))
            if not hits:
                return False, f"expected sandbox file not found: {file_exists}"
        return True, "declarative assertion passed"

    return assertion


_ENV_FLAGS = {
    "none": {"requires_aws": False, "uses_mock": False},
    "real_aws": {"requires_aws": True, "uses_mock": False},
    "mock": {"requires_aws": False, "uses_mock": True},
}


def _inline_task(entry: dict, model: str | None) -> Task:
    setup_files = entry.get("setup_files", {})

    def setup(workdir: Path, ctx: dict, _files=setup_files) -> None:
        for rel, content in _files.items():
            (workdir / rel).write_text(content)

    env_flags = _ENV_FLAGS[entry.get("env", "none")]
    suffix = f"-{_short_model(model)}" if model else ""
    return Task(
        id=entry["id"] + suffix,
        prompt=entry["prompt"],
        allowed_tools=entry.get("tools", ["Bash", "Read", "Edit", "Write"]),
        setup=setup,
        assertion=_declarative_assertion(entry.get("assert", {})),
        max_turns=entry.get("max_turns", 12),
        model=model,
        **env_flags,
    )


def load_suite_file(path: str | Path, resolve_ref, resolve_ref_suite) -> list[Task]:
    """Parse a JSON suite file into Tasks.

    `resolve_ref(name) -> Task` and `resolve_ref_suite(name) -> list[Task]` are
    injected by the runner (which owns the task/suite registries) to avoid a
    circular import.
    """
    entries = json.loads(Path(path).read_text())
    if not isinstance(entries, list):
        raise ValueError("suite file must be a JSON array of test-case objects")

    tasks: list[Task] = []
    for entry in entries:
        # model sweep: "models": [...] expands; else single "model"
        models = entry.get("models") or [entry.get("model")]
        models = [resolve_model(m) for m in models]

        for model in models:
            if "ref" in entry:
                t = resolve_ref(entry["ref"])
                t.model = model
                if "k" in entry:
                    entry["_k"] = entry["k"]  # surfaced by runner if needed
                t.id = f"{t.id}-{_short_model(model)}" if model else t.id
                tasks.append(t)
            elif "ref_suite" in entry:
                for t in resolve_ref_suite(entry["ref_suite"]):
                    t.model = model
                    t.id = f"{t.id}-{_short_model(model)}" if model else t.id
                    tasks.append(t)
            else:
                tasks.append(_inline_task(entry, model))
    return tasks
