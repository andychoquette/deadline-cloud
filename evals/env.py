"""Environment provisioning/teardown (design doc 4.5).

POC: an isolated temp sandbox dir per run. The Task's setup() populates it with
fixtures, and the agent runs with cwd there. No AWS, no farm.

The real-AWS implementation (ephemeral run-id-tagged farm + reaper) replaces the
body of provision()/teardown() behind this same plain-module boundary.
"""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator


@contextmanager
def provision(
    task_id: str,
    setup: Callable[[Path], None],
    snapshot_to: Path | None = None,
) -> Iterator[Path]:
    """Create an isolated sandbox, run setup(), yield the path, always tear down.

    If `snapshot_to` is given, the sandbox contents are copied there just before
    teardown so the agent's output survives for artifact review.
    """
    workdir = Path(tempfile.mkdtemp(prefix=f"deval-{task_id}-"))
    try:
        setup(workdir)
        yield workdir
    finally:
        if snapshot_to is not None:
            snapshot_to.mkdir(parents=True, exist_ok=True)
            shutil.copytree(workdir, snapshot_to, dirs_exist_ok=True)
        shutil.rmtree(workdir, ignore_errors=True)
