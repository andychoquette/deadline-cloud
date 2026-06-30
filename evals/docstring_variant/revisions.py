"""Candidate docstring revisions, keyed by variant name then command path.

Command path is space-joined, e.g. "bundle submit". Each entry may set the
command `help` and/or per-option `options[<param_name>]` help.

The hypothesis under test: more explicit, agent-friendly help (concrete examples,
explicit mention that a bundle is a DIRECTORY containing template.yaml, the
submit->wait lifecycle) reduces the agent's turns/tool-calls and raises success.

These are illustrative starting points; the report recommends further revisions
based on where the agent actually struggled.
"""

from __future__ import annotations

REVISIONS = {
    "revised": {
        "bundle submit": {
            "help": (
                "Submit an Open Job Description (OpenJD) job bundle to a Deadline "
                "Cloud queue.\n\n"
                "JOB_BUNDLE_DIR is a DIRECTORY (not a file) that must contain a "
                "`template.yaml` (the OpenJD job template, specificationVersion "
                "'jobtemplate-2023-09'). It may optionally contain "
                "`parameter_values.yaml` and `asset_references.yaml`.\n\n"
                "Example:\n"
                "  deadline bundle submit ./my_job --yes\n\n"
                "The command returns a job id (job-xxxx). Use `deadline job get "
                "--job-id <id>` to check its taskRunStatus until it reaches a "
                "terminal state (SUCCEEDED / FAILED / CANCELED)."
            ),
            "options": {
                "yes": "Skip the interactive confirmation prompt. Required for non-interactive/scripted use.",
                "name": "Override the job name. Defaults to the `name` field in template.yaml.",
                "priority": "Job priority 1-100 (default 50). Higher runs first.",
            },
        },
        "job get": {
            "help": (
                "Show full details of a job, including its lifecycleStatus and "
                "taskRunStatus.\n\n"
                "To diagnose a FAILED job: read `taskRunStatus` and "
                "`taskRunStatusCounts` here, then run `deadline job logs --job-id "
                "<id>` to see the session logs (stdout/stderr of the task), which "
                "usually contain the actual error.\n\n"
                "Example:\n  deadline job get --job-id job-xxxx"
            ),
            "options": {
                "job_id": "The job id (job-xxxx) returned by `deadline bundle submit`.",
            },
        },
        "job logs": {
            "help": (
                "Print the CloudWatch session logs for a job -- this is where the "
                "task's stdout/stderr (and the actual failure cause) appear.\n\n"
                "Use this when a job's taskRunStatus is FAILED to find out WHY it "
                "failed.\n\n"
                "Example:\n  deadline job logs --job-id job-xxxx --limit 200"
            ),
        },
    }
}
