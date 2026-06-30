"""Admin / onboarding tasks against the AwsInABox mock (mocked-aws env).

The agent uses the RAW `aws deadline` CLI (the high-level `deadline` CLI has no
create-farm/queue/fleet) pointed at the local emulator. We grade by reading the
resulting state back through the mock -- did the resource actually get created?

Each task sets ctx['env'] so the runner injects AWS_ENDPOINT_URL etc. into the
agent's subprocess. Tasks require the mock to be up (checked by the runner).
Exposed via make_tasks().
"""

from __future__ import annotations

from pathlib import Path

from .. import mock_aws
from ..task import Task

_TOOLS = ["Bash"]


def _unique(ctx: dict, kind: str) -> str:
    """A per-run unique marker so assertions match the AGENT's creation, not leftovers."""
    return f"deval-{kind}-{ctx['variant']}-{ctx['run_idx']}-{id(ctx) % 100000}"


def _farms_named(name: str) -> list[dict]:
    farms = (mock_aws.aws_deadline(["list-farms"]) or {}).get("farms", [])
    return [f for f in farms if f.get("displayName") == name]


def make_tasks() -> list[Task]:
    # --- create a farm (unique name injected into the prompt) ---
    def setup_farm(workdir: Path, ctx: dict) -> None:
        ctx["name"] = _unique(ctx, "farm")
        ctx["prompt"] = (
            f"Using the `aws deadline` CLI, create a new Deadline Cloud farm with the "
            f"display name '{ctx['name']}'. Confirm in your final answer with the new farm ID."
        )

    def assert_create_farm(result, ctx):  # noqa: ANN001
        match = _farms_named(ctx["name"])
        if match:
            return True, f"farm '{ctx['name']}' created: {match[-1]['farmId']}"
        return False, f"no farm named '{ctx['name']}' found in mock state"

    # --- create farm THEN queue under it (2-step) ---
    def setup_queue(workdir: Path, ctx: dict) -> None:
        ctx["farm_name"] = _unique(ctx, "qfarm")
        ctx["queue_name"] = _unique(ctx, "queue")
        ctx["prompt"] = (
            f"Using the `aws deadline` CLI: first create a farm named '{ctx['farm_name']}', "
            f"then create a queue named '{ctx['queue_name']}' inside that farm. Report both IDs."
        )

    def assert_create_queue(result, ctx):  # noqa: ANN001
        farms = _farms_named(ctx["farm_name"])
        if not farms:
            return False, f"farm '{ctx['farm_name']}' was not created"
        fid = farms[-1]["farmId"]
        queues = (mock_aws.aws_deadline(["list-queues", "--farm-id", fid]) or {}).get("queues", [])
        match = [q for q in queues if q.get("displayName") == ctx["queue_name"]]
        if match:
            return True, f"queue '{ctx['queue_name']}' created under {fid}: {match[-1]['queueId']}"
        return False, f"queue '{ctx['queue_name']}' not found under farm {fid}"

    # --- end-to-end onboarding: farm -> queue -> fleet ---
    def setup_e2e(workdir: Path, ctx: dict) -> None:
        ctx["farm_name"] = _unique(ctx, "e2efarm")
        ctx["queue_name"] = _unique(ctx, "e2equeue")
        ctx["fleet_name"] = _unique(ctx, "e2efleet")
        ctx["prompt"] = (
            f"Set up a new Deadline Cloud environment using the `aws deadline` CLI: create a "
            f"farm named '{ctx['farm_name']}', then a queue named '{ctx['queue_name']}' in it, "
            f"then a fleet named '{ctx['fleet_name']}' in the same farm. Report all three IDs."
        )

    def assert_e2e(result, ctx):  # noqa: ANN001
        farms = _farms_named(ctx["farm_name"])
        if not farms:
            return False, f"farm '{ctx['farm_name']}' not created"
        fid = farms[-1]["farmId"]
        queues = (mock_aws.aws_deadline(["list-queues", "--farm-id", fid]) or {}).get("queues", [])
        fleets = (mock_aws.aws_deadline(["list-fleets", "--farm-id", fid]) or {}).get("fleets", [])
        q_ok = any(q.get("displayName") == ctx["queue_name"] for q in queues)
        f_ok = any(f.get("displayName") == ctx["fleet_name"] for f in fleets)
        if q_ok and f_ok:
            return True, f"e2e ok: farm {fid} + queue + fleet all created"
        return False, f"incomplete e2e (queue_ok={q_ok}, fleet_ok={f_ok})"

    # --- teardown: harness pre-creates a uniquely-named farm; agent deletes it ---
    def prep_teardown(ctx: dict) -> None:
        ctx["name"] = _unique(ctx, "td")
        out = mock_aws.aws_deadline(["create-farm", "--display-name", ctx["name"]])
        ctx["farm_id"] = (out or {}).get("farmId")

    def setup_teardown(workdir: Path, ctx: dict) -> None:
        ctx["prompt"] = (
            f"A Deadline Cloud farm named '{ctx['name']}' needs to be torn down. Using the "
            f"`aws deadline` CLI, find that farm and delete it. Confirm deletion."
        )

    def assert_teardown(result, ctx):  # noqa: ANN001
        fid = ctx.get("farm_id")
        if not fid:
            return False, "harness failed to pre-create the farm to delete"
        farms = (mock_aws.aws_deadline(["list-farms"]) or {}).get("farms", [])
        if not any(f.get("farmId") == fid for f in farms):
            return True, f"farm {fid} ('{ctx['name']}') successfully deleted"
        return False, f"farm {fid} still present -- not deleted"

    specs = [
        ("admin_create_farm", setup_farm, assert_create_farm, None),
        ("admin_create_queue", setup_queue, assert_create_queue, None),
        ("admin_e2e_onboarding", setup_e2e, assert_e2e, None),
        ("admin_delete_farm", setup_teardown, assert_teardown, prep_teardown),
    ]

    tasks = []
    for tid, setup, assertion, prepare in specs:
        tasks.append(Task(
            id=tid, prompt="",  # prompt is built per-run in setup() with the unique name
            allowed_tools=_TOOLS,
            setup=setup, assertion=assertion, prepare=prepare,
            requires_aws=False,   # uses MOCK, not real AWS auth
            uses_mock=True,
            max_turns=15,
        ))
    return tasks
