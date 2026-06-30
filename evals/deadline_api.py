"""Thin wrapper over the `deadline` CLI for the harness's own use.

This is the harness driving Deadline Cloud directly (submit fixtures, poll status,
fetch logs for assertions) -- distinct from the *agent* driving the CLI. All calls
are subprocess invocations of the installed `deadline` binary, parsed from YAML.

SAFETY: only submit + read operations. Never deletes or modifies farms/queues/fleets.
The harness submits to the operator's PRE-EXISTING farm/queue/fleet (jobs are the
isolation unit locally, not farms).
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

# Deadline job lifecycle/run statuses we treat as terminal.
TERMINAL_RUN_STATUSES = {"SUCCEEDED", "FAILED", "CANCELED"}


@dataclass
class JobStatus:
    job_id: str
    name: str
    lifecycle_status: str
    task_run_status: str
    raw: dict

    @property
    def is_terminal(self) -> bool:
        return self.task_run_status in TERMINAL_RUN_STATUSES

    @property
    def succeeded(self) -> bool:
        return self.task_run_status == "SUCCEEDED"


def submit_bundle(bundle_dir: Path, *, name: str | None = None) -> str:
    """Submit a job bundle; return the job id. Raises on submit failure."""
    cmd = ["deadline", "bundle", "submit", str(bundle_dir), "--yes"]
    if name:
        cmd += ["--name", name]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"submit failed: {proc.stderr.strip() or proc.stdout.strip()}")
    # The job id is the last token of the form job-xx­xx in stdout.
    for token in reversed(proc.stdout.split()):
        if token.startswith("job-"):
            return token
    raise RuntimeError(f"could not parse job id from submit output:\n{proc.stdout}")


def get_job(job_id: str) -> JobStatus:
    """Read a job's status (YAML output of `deadline job get`)."""
    proc = subprocess.run(
        ["deadline", "job", "get", "--job-id", job_id],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"job get failed: {proc.stderr.strip()}")
    # Strip any leading INFO log lines before the YAML document.
    lines = [ln for ln in proc.stdout.splitlines() if not ln.startswith("INFO:")]
    doc = yaml.safe_load("\n".join(lines)) or {}
    return JobStatus(
        job_id=doc.get("jobId", job_id),
        name=doc.get("name", ""),
        lifecycle_status=doc.get("lifecycleStatus", ""),
        task_run_status=doc.get("taskRunStatus", ""),
        raw=doc,
    )


def wait_for_terminal(
    job_id: str,
    *,
    timeout_s: int = 900,
    poll_s: int = 15,
) -> JobStatus:
    """Poll until the job reaches a terminal run status or timeout.

    timeout is generous because a scaled-to-zero fleet must cold-start a worker.
    """
    deadline_t = time.monotonic() + timeout_s
    status = get_job(job_id)
    while not status.is_terminal:
        if time.monotonic() > deadline_t:
            raise TimeoutError(
                f"job {job_id} not terminal after {timeout_s}s "
                f"(last status: {status.task_run_status})"
            )
        time.sleep(poll_s)
        status = get_job(job_id)
    return status


def _run_yaml(args: list[str]):
    """Run a `deadline` read command and parse its YAML output (strip INFO: lines)."""
    proc = subprocess.run(["deadline", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"`deadline {' '.join(args)}` failed: {proc.stderr.strip()}")
    lines = [ln for ln in proc.stdout.splitlines() if not ln.startswith("INFO:")]
    return yaml.safe_load("\n".join(lines))


def get_farm() -> dict:
    return _run_yaml(["farm", "get"]) or {}


def get_queue() -> dict:
    return _run_yaml(["queue", "get"]) or {}


def list_fleets() -> list[dict]:
    out = _run_yaml(["fleet", "list"]) or []
    return out if isinstance(out, list) else out.get("fleets", [])


def get_fleet(fleet_id: str) -> dict:
    return _run_yaml(["fleet", "get", "--fleet-id", fleet_id]) or {}


def list_jobs() -> list[dict]:
    """List jobs in the queue. `job list` prints a 'Displaying N of M' header before
    the YAML list, and timestamp values aren't quoted -- so strip the header and drop
    the noisy timestamp lines before parsing (we only need name/jobId/taskRunStatus)."""
    proc = subprocess.run(["deadline", "job", "list"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"job list failed: {proc.stderr.strip()}")
    keep_keys = ("name:", "jobId:", "taskRunStatus:", "lifecycleStatus:")
    lines = []
    for ln in proc.stdout.splitlines():
        if ln.startswith("INFO:") or ln.startswith("Displaying"):
            continue
        stripped = ln.strip()
        if stripped.startswith("- ") or any(stripped.startswith(k) for k in keep_keys):
            lines.append(ln)
    out = yaml.safe_load("\n".join(lines)) or []
    return out if isinstance(out, list) else out.get("jobs", [])


def get_job_logs(job_id: str, *, limit: int = 200) -> str:
    """Fetch session logs for a job (best-effort; returns '' on failure)."""
    proc = subprocess.run(
        ["deadline", "job", "logs", "--job-id", job_id, "--limit", str(limit)],
        capture_output=True,
        text=True,
    )
    return proc.stdout if proc.returncode == 0 else ""
