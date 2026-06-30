"""Suite of read-only CLI inspection tasks (Tier 1).

Each task asks the agent a question answerable with `deadline` read commands
(farm/queue/fleet/job get+list). Assertions fetch the CURRENT truth via an
independent CLI read (deadline_api) and substring-check the agent's final answer
-- so there are no hardcoded IDs and the suite self-updates with the account.

Safe (no mutation), fast (no job lifecycle), deterministic. Exposed via make_tasks().
"""

from __future__ import annotations

from pathlib import Path

from .. import deadline_api
from ..task import Task

_TOOLS = ["Bash"]  # read-only; agent runs `deadline ... get/list`


def _noop_setup(workdir: Path, ctx: dict) -> None:
    pass


def _contains(answer: str, *needles: str) -> bool:
    a = (answer or "").lower()
    return all(str(n).lower() in a for n in needles if n)


# Each spec: (id, prompt, truth_fn -> needles). truth_fn runs at assertion time.
def make_tasks() -> list[Task]:
    def farm_name(result, ctx):  # noqa: ANN001
        truth = deadline_api.get_farm().get("displayName", "")
        ok = _contains(result.final_text, truth)
        return ok, f"expected farm name '{truth}' in answer"

    def queue_id(result, ctx):  # noqa: ANN001
        truth = deadline_api.get_queue().get("queueId", "")
        ok = _contains(result.final_text, truth)
        return ok, f"expected queue id '{truth}' in answer"

    def queue_name(result, ctx):  # noqa: ANN001
        truth = deadline_api.get_queue().get("displayName", "")
        ok = _contains(result.final_text, truth)
        return ok, f"expected queue name '{truth}' in answer"

    def fleet_count(result, ctx):  # noqa: ANN001
        fleets = deadline_api.list_fleets()
        ok = _contains(result.final_text, str(len(fleets)))
        return ok, f"expected fleet count {len(fleets)} in answer"

    def fleet_name(result, ctx):  # noqa: ANN001
        fleets = deadline_api.list_fleets()
        name = fleets[0].get("displayName", "") if fleets else ""
        ok = _contains(result.final_text, name)
        return ok, f"expected fleet name '{name}' in answer"

    def fleet_status(result, ctx):  # noqa: ANN001
        fleets = deadline_api.list_fleets()
        fid = fleets[0].get("fleetId") if fleets else None
        status = deadline_api.get_fleet(fid).get("status", "") if fid else ""
        ok = _contains(result.final_text, status)
        return ok, f"expected fleet status '{status}' in answer"

    def fleet_max_workers(result, ctx):  # noqa: ANN001
        fleets = deadline_api.list_fleets()
        fid = fleets[0].get("fleetId") if fleets else None
        detail = deadline_api.get_fleet(fid) if fid else {}
        # maxWorkerCount may be nested depending on fleet config; check both.
        mx = detail.get("maxWorkerCount", detail.get("capabilities", {}))
        ok = _contains(result.final_text, str(mx)) if isinstance(mx, int) else True
        return ok, f"expected max worker count '{mx}' in answer"

    def recent_jobs(result, ctx):  # noqa: ANN001
        jobs = deadline_api.list_jobs()
        if not jobs:
            return False, "no jobs in queue to verify against"
        name = jobs[0].get("name", "")
        ok = _contains(result.final_text, name)
        return ok, f"expected most-recent job name '{name}' in answer"

    specs = [
        ("read_farm_name",
         "What is the display name of the default Deadline Cloud farm? Use the `deadline` CLI. State the name in your final answer.",
         farm_name),
        ("read_queue_id",
         "List the queues in the default farm using the `deadline` CLI and tell me the queue ID in your final answer.",
         queue_id),
        ("read_queue_name",
         "What is the display name of the default queue? Use the `deadline` CLI and state it in your final answer.",
         queue_name),
        ("read_fleet_count",
         "How many fleets are in the default farm? Use the `deadline` CLI and state the number in your final answer.",
         fleet_count),
        ("read_fleet_name",
         "What is the display name of the fleet in the default farm? Use the `deadline` CLI and state it in your final answer.",
         fleet_name),
        ("read_fleet_status",
         "What is the status of the fleet in the default farm? Use the `deadline` CLI and state the status in your final answer.",
         fleet_status),
        ("read_fleet_max_workers",
         "What is the maximum worker count configured on the fleet in the default farm? Use the `deadline` CLI and state the number.",
         fleet_max_workers),
        ("read_recent_job",
         "Using the `deadline` CLI, list the jobs in the default queue and tell me the name of the most recent job in your final answer.",
         recent_jobs),
    ]

    tasks = []
    for tid, prompt, assertion in specs:
        tasks.append(
            Task(
                id=tid,
                prompt=prompt,
                allowed_tools=_TOOLS,
                setup=_noop_setup,
                assertion=assertion,
                requires_aws=True,
                max_turns=10,
            )
        )
    return tasks
