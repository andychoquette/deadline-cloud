"""Real-AWS task: agent authors a job bundle from scratch; harness submits it
and waits for SUCCEEDED.

This tests the agent's ability to produce a *runnable* bundle (not merely
schema-valid): the job actually executes on a worker. The agent is told to author
the bundle but NOT to submit it -- the harness submits in finalize() so submission
is controlled and identical across runs (isolating the agent's authoring quality).
"""

from __future__ import annotations

from pathlib import Path

from .. import deadline_api

PROMPT = (
    "Create an Open Job Description (OpenJD) job bundle for AWS Deadline Cloud in "
    "the current directory. The job must have a single step that runs a bash "
    "command printing a short greeting (for example, `echo \"hello from deadline\"`). "
    "Write the job template to a file named `template.yaml` in this directory. "
    "Use the `deadline` CLI's help (e.g. `deadline bundle submit --help`) if you "
    "need to understand the expected bundle format. Do NOT submit the job yourself "
    "-- only author template.yaml. Keep it minimal and valid."
)


def setup(workdir: Path, ctx: dict) -> None:
    # Empty sandbox; the agent authors template.yaml from scratch.
    ctx["bundle_dir"] = workdir


def finalize(result, ctx: dict) -> None:  # noqa: ANN001
    """After the agent runs, submit the bundle it authored and wait for terminal."""
    bundle_dir: Path = ctx["bundle_dir"]
    template = bundle_dir / "template.yaml"
    if not template.exists():
        ctx["submit_error"] = "agent did not create template.yaml"
        return
    try:
        job_id = deadline_api.submit_bundle(bundle_dir, name=f"deval-author-{ctx['run_idx']}")
        ctx["job_id"] = job_id
        status = deadline_api.wait_for_terminal(job_id, timeout_s=900)
        ctx["job_status"] = status.task_run_status
    except Exception as e:  # submit/validation/timeout
        ctx["submit_error"] = str(e)


def assertion(result, ctx: dict) -> tuple[bool, str]:  # noqa: ANN001
    if "submit_error" in ctx:
        return False, f"submit/run failed: {ctx['submit_error']}"
    status = ctx.get("job_status")
    if status == "SUCCEEDED":
        return True, f"job {ctx.get('job_id')} SUCCEEDED"
    return False, f"job {ctx.get('job_id')} ended {status}"
