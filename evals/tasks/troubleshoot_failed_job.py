"""Real-AWS task: harness submits a guaranteed-fail job; the agent diagnoses it.

prepare() submits a pre-cooked bundle whose task runs `exit 1`, and waits until it
reaches FAILED. The agent is then asked to investigate that job id using the
`deadline` CLI (`job get`, `job logs`) and report why it failed. The assertion
checks the agent's final diagnosis identifies the failure (non-zero exit / command
failed) -- adjudicated programmatically against the known root cause.
"""

from __future__ import annotations

from pathlib import Path

from .. import deadline_api

# Pre-cooked bundle: a task that fails immediately and deterministically.
FAILING_TEMPLATE = """\
specificationVersion: 'jobtemplate-2023-09'
name: deval-failing-job
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
        echo "starting work"
        echo "fatal: widget alignment failed" >&2
        exit 1
"""

PROMPT_TEMPLATE = (
    "A Deadline Cloud job with id {job_id} has failed. Investigate why it failed "
    "using the `deadline` CLI (for example `deadline job get` and `deadline job "
    "logs`). Then state clearly, in your final message, whether the job failed and "
    "what the root cause was. Be specific about the failure."
)


def prepare(ctx: dict) -> None:
    """Submit the failing job and wait for it to reach FAILED before the agent runs."""
    import tempfile

    bundle_dir = Path(tempfile.mkdtemp(prefix="deval-failbundle-"))
    (bundle_dir / "template.yaml").write_text(FAILING_TEMPLATE)
    job_id = deadline_api.submit_bundle(bundle_dir, name=f"deval-fail-{ctx['run_idx']}")
    ctx["job_id"] = job_id
    status = deadline_api.wait_for_terminal(job_id, timeout_s=900)
    ctx["seeded_status"] = status.task_run_status  # expected FAILED


def setup(workdir: Path, ctx: dict) -> None:
    # Inject the seeded job id into the prompt; nothing to place in the sandbox.
    ctx["prompt"] = PROMPT_TEMPLATE.format(job_id=ctx["job_id"])


def assertion(result, ctx: dict) -> tuple[bool, str]:  # noqa: ANN001
    if ctx.get("seeded_status") != "FAILED":
        return False, f"seed job did not FAIL (was {ctx.get('seeded_status')}) -- inconclusive"

    text = (result.final_text or "").lower()
    # The agent must recognize the job failed AND point at the cause.
    recognized_fail = any(w in text for w in ("fail", "error", "exit 1", "non-zero", "unsuccessful"))
    named_cause = any(
        w in text for w in ("exit", "exit code", "exit 1", "non-zero", "widget alignment", "command")
    )
    if recognized_fail and named_cause:
        return True, "agent correctly diagnosed the failure (non-zero exit / command failed)"
    return False, f"diagnosis incomplete (recognized_fail={recognized_fail}, named_cause={named_cause})"
