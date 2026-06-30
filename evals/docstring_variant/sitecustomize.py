"""Injected via PYTHONPATH to patch the `deadline` CLI's help text at import time.

This is the A/B *variable under test* (design doc, revised): when
DEADLINE_EVALS_HELP=revised, we rewrite Click command/option help strings to a
candidate version before the CLI renders --help. Baseline (unset/"baseline")
leaves the stock help untouched.

Python auto-imports `sitecustomize` if it's found on sys.path, so putting this
directory on PYTHONPATH means every `deadline ...` subprocess picks it up with
zero changes to the installed package. The revisions live in revisions.py.
"""

from __future__ import annotations

import os


def _apply() -> None:
    variant = os.environ.get("DEADLINE_EVALS_HELP", "baseline").lower()
    if variant in ("", "baseline", "stock"):
        return

    try:
        from deadline.client.cli import main as cli_main  # the root click.Group
    except Exception:
        return  # not a deadline invocation, or CLI not importable

    revs = _load_variant(variant)
    if not revs:
        return

    _patch_group(cli_main, revs, prefix="")


def _load_variant(variant: str) -> dict:
    """Resolve a variant's revisions, from the static module or a JSON override.

    DEADLINE_EVALS_REVISIONS_FILE, if set, points at a JSON file mapping the same
    {command_path: {help, options}} shape -- used for LLM-autodrafted variants.
    Otherwise fall back to the hand-written REVISIONS in revisions.py.
    """
    import json
    import os

    override = os.environ.get("DEADLINE_EVALS_REVISIONS_FILE")
    if override and os.path.exists(override):
        try:
            with open(override) as f:
                data = json.load(f)
            return data.get(variant, {})
        except Exception:
            return {}

    try:
        from revisions import REVISIONS  # noqa: PLC0415 (same dir, on PYTHONPATH)
    except Exception:
        return {}
    return REVISIONS.get(variant, {})


def _patch_group(group, revs: dict, prefix: str) -> None:
    """Recursively rewrite .help on commands and option .help on params."""
    commands = getattr(group, "commands", {})
    for name, cmd in commands.items():
        path = f"{prefix}{name}"
        cmd_rev = revs.get(path)
        if isinstance(cmd_rev, dict):
            if "help" in cmd_rev:
                cmd.help = cmd_rev["help"]
            opt_revs = cmd_rev.get("options", {})
            for param in getattr(cmd, "params", []):
                pname = getattr(param, "name", None)
                if pname in opt_revs:
                    param.help = opt_revs[pname]
        # Recurse into subgroups (e.g. `bundle`, `job`).
        if getattr(cmd, "commands", None):
            _patch_group(cmd, revs, prefix=f"{path} ")


_apply()
