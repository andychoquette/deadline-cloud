"""Tier-2 mutation tasks -- each operates ONLY on its own disposable job.

These mutate real AWS state, so every task's prepare() submits a fresh throwaway
job and the agent acts on THAT job id only. Pre-existing farm/queue/fleet and other
jobs are never touched. Exposed via make_tasks().
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from .. import deadline_api
from ..task import Task

_TOOLS = ["Bash", "Read"]

# A job that writes an output file (for the download-output task).
OUTPUT_TEMPLATE = """\
specificationVersion: 'jobtemplate-2023-09'
name: deval-output-job
parameterDefinitions:
- name: OutDir
  type: PATH
  objectType: DIRECTORY
  dataFlow: OUT
steps:
- name: WriteOutput
  script:
    actions:
      onRun:
        command: bash
        args: ['{{Task.File.Run}}']
    embeddedFiles:
    - name: Run
      type: TEXT
      data: |
        echo "deval output payload" > '{{Param.OutDir}}/result.txt'
"""

# A long-ish job so the agent can cancel it before it finishes.
LONG_TEMPLATE = """\
specificationVersion: 'jobtemplate-2023-09'
name: deval-long-job
steps:
- name: Sleep
  script:
    actions:
      onRun:
        command: bash
        args: ['{{Task.File.Run}}']
    embeddedFiles:
    - name: Run
      type: TEXT
      data: |
        sleep 600
"""

# A failing job (for requeue) -- fails fast so it's terminal quickly.
FAIL_TEMPLATE = """\
specificationVersion: 'jobtemplate-2023-09'
name: deval-requeue-job
steps:
- name: FailFast
  script:
    actions:
      onRun:
        command: bash
        args: ['{{Task.File.Run}}']
    embeddedFiles:
    - name: Run
      type: TEXT
      data: |
        exit 1
"""


def _submit_tmp(template: str, name: str) -> str:
    d = Path(tempfile.mkdtemp(prefix="deval-mutbundle-"))
    (d / "template.yaml").write_text(template)
    return deadline_api.submit_bundle(d, name=name)


def make_tasks() -> list[Task]:
    # --- download-output: agent downloads a completed job's output ---
    def prep_download(ctx: dict) -> None:
        jid = _submit_tmp(OUTPUT_TEMPLATE, f"deval-out-{ctx['run_idx']}")
        ctx["job_id"] = jid
        st = deadline_api.wait_for_terminal(jid, timeout_s=900)
        ctx["seeded_status"] = st.task_run_status

    def setup_download(workdir: Path, ctx: dict) -> None:
        ctx["prompt"] = (
            f"A Deadline Cloud job {ctx['job_id']} has completed and produced output "
            f"files. Use the `deadline` CLI to download this job's output into the "
            f"current directory. Confirm in your final answer that you downloaded it."
        )

    def assert_download(result, ctx: dict):  # noqa: ANN001
        if ctx.get("seeded_status") != "SUCCEEDED":
            return False, f"seed job not SUCCEEDED ({ctx.get('seeded_status')}) -- inconclusive"
        # The agent ran in a sandbox; check any result.txt landed under its workdir.
        hits = list(Path(result.workdir).rglob("result.txt")) if result.workdir else []
        if hits:
            return True, f"downloaded output ({hits[0].name})"
        return False, "no downloaded output file (result.txt) found in sandbox"

    # --- requeue-tasks: agent requeues a failed job's tasks ---
    def prep_requeue(ctx: dict) -> None:
        jid = _submit_tmp(FAIL_TEMPLATE, f"deval-rq-{ctx['run_idx']}")
        ctx["job_id"] = jid
        st = deadline_api.wait_for_terminal(jid, timeout_s=900)
        ctx["seeded_status"] = st.task_run_status  # expect FAILED

    def setup_requeue(workdir: Path, ctx: dict) -> None:
        ctx["prompt"] = (
            f"A Deadline Cloud job {ctx['job_id']} has FAILED tasks. Use the `deadline` "
            f"CLI to requeue (retry) the failed tasks for this job. Confirm in your "
            f"final answer that you requeued them."
        )

    def assert_requeue(result, ctx: dict):  # noqa: ANN001
        if ctx.get("seeded_status") != "FAILED":
            return False, f"seed job not FAILED ({ctx.get('seeded_status')}) -- inconclusive"
        # After requeue, the job's tasks leave FAILED (go READY/RUNNING/etc).
        st = deadline_api.get_job(ctx["job_id"])
        if st.task_run_status != "FAILED":
            return True, f"tasks requeued (status now {st.task_run_status})"
        # Fall back to the agent asserting it ran the command successfully.
        return False, "job tasks still FAILED -- requeue not effective"

    # --- cancel: agent cancels a long-running job ---
    def prep_cancel(ctx: dict) -> None:
        jid = _submit_tmp(LONG_TEMPLATE, f"deval-cancel-{ctx['run_idx']}")
        ctx["job_id"] = jid  # do NOT wait -- it's a 10-min sleep; agent cancels it

    def setup_cancel(workdir: Path, ctx: dict) -> None:
        ctx["prompt"] = (
            f"A Deadline Cloud job {ctx['job_id']} is running and needs to be stopped. "
            f"Use the `deadline` CLI to cancel this job. Confirm in your final answer."
        )

    def assert_cancel(result, ctx: dict):  # noqa: ANN001
        st = deadline_api.get_job(ctx["job_id"])
        # Cancel drives the job toward CANCELED.
        if "CANCEL" in (st.task_run_status or "").upper() or st.task_run_status == "CANCELED":
            return True, f"job canceled (status {st.task_run_status})"
        return False, f"job not canceled (status {st.task_run_status})"

    return [
        Task(id="mutate_download_output", prompt="", allowed_tools=_TOOLS,
             setup=setup_download, assertion=assert_download, prepare=prep_download,
             requires_aws=True, max_turns=12),
        Task(id="mutate_requeue_tasks", prompt="", allowed_tools=_TOOLS,
             setup=setup_requeue, assertion=assert_requeue, prepare=prep_requeue,
             requires_aws=True, max_turns=12),
        Task(id="mutate_cancel_job", prompt="", allowed_tools=_TOOLS,
             setup=setup_cancel, assertion=assert_cancel, prepare=prep_cancel,
             requires_aws=True, max_turns=12),
    ]
