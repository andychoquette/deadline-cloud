"""Publish guardrail (option A: detect + refuse, NEVER auto-create).

Before any docstring patch could be pushed, this verifies the target git repo's
`origin` is a FORK of aws-deadline/deadline-cloud -- not the upstream itself. If it
is upstream, or not a fork, or gh is unavailable, it REFUSES with guidance and does
nothing. It never creates a fork, never pushes, never opens a PR on its own.

The contribution model for the public aws-deadline/deadline-cloud repo is
fork -> branch -> PR upstream; this enforces that we can't accidentally act on
upstream.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

UPSTREAM = "aws-deadline/deadline-cloud"


@dataclass
class RepoCheck:
    ok: bool
    message: str
    nameWithOwner: str | None = None
    is_fork: bool = False
    parent: str | None = None


def check_target_repo(repo_dir: str) -> RepoCheck:
    """Classify the git repo at repo_dir. ok=True only if it's a fork of upstream."""
    # gh required for parent/fork metadata.
    if subprocess.run(["which", "gh"], capture_output=True).returncode != 0:
        return RepoCheck(False, "GitHub CLI `gh` not found. Install it to publish, or apply the patch manually.")

    proc = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner,isFork,parent"],
        cwd=repo_dir, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return RepoCheck(False, f"`gh repo view` failed in {repo_dir}: {proc.stderr.strip()}")

    data = json.loads(proc.stdout)
    name = data.get("nameWithOwner")
    is_fork = data.get("isFork", False)
    parent = data.get("parent") or {}
    parent_name = parent.get("nameWithOwner") if isinstance(parent, dict) else None

    # Refuse: this IS upstream.
    if name == UPSTREAM:
        return RepoCheck(
            False,
            f"REFUSING: origin is the upstream {UPSTREAM}, not a fork. "
            f"Create your own fork and point this checkout at it:\n"
            f"  gh repo fork {UPSTREAM} --clone\n"
            f"then re-run against the fork.",
            nameWithOwner=name,
        )

    # Refuse: not a fork at all, or a fork of something else.
    if not is_fork or parent_name != UPSTREAM:
        return RepoCheck(
            False,
            f"REFUSING: {name} is not a fork of {UPSTREAM} "
            f"(isFork={is_fork}, parent={parent_name}). "
            f"Publishing only proceeds against a fork of {UPSTREAM}.",
            nameWithOwner=name, is_fork=is_fork, parent=parent_name,
        )

    return RepoCheck(
        True,
        f"OK: {name} is a fork of {UPSTREAM}. Safe to branch + commit the patch here. "
        f"(This tool stops before opening the PR -- review, then run `gh pr create`.)",
        nameWithOwner=name, is_fork=True, parent=parent_name,
    )
