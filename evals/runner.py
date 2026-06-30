"""Runner: the eval loop with the docstring A/B variable (design doc 4.2, revised).

Runs each task under TWO variants -- baseline (stock `deadline` help) and revised
(monkeypatched help) -- K times each, then applies the paired telemetry gate to
the baseline-vs-revised deltas. The variable under test is the CLI's docstrings.

Artifacts under evals/output/<task>/<timestamp>/:
    summary.json            per-variant aggregates + paired gate + recommendations
    report.html             human-readable comparison
    <variant>/run-<n>/...   per-run telemetry, events, workspace snapshot

Usage:
    python -m evals.runner --task author_and_submit --k 2
    python -m evals.runner --task job_bundle_validate --k 2          # offline
    python -m evals.runner --task troubleshoot_failed_job --k 1
"""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import autodraft, env, patchgen, recommend, report, scorer
from .harness import RunResult, run_claude_code
from .task import Task

OUTPUT_ROOT = Path(__file__).parent / "output"
VARIANT_DIR = Path(__file__).parent / "docstring_variant"

TASK_MODULES = {
    "job_bundle_validate": "evals.tasks.job_bundle_validate",       # offline
    "author_and_submit": "evals.tasks.author_and_submit",           # real AWS
    "troubleshoot_failed_job": "evals.tasks.troubleshoot_failed_job",  # real AWS
}

# Suite modules expose make_tasks() -> list[Task]. Selectable by suite name, or by
# the individual task ids they contain.
SUITE_MODULES = {
    "cli_read": "evals.tasks.cli_read",        # 8 read-only inspection tasks (real AWS)
    "cli_mutate": "evals.tasks.cli_mutate",    # 3 disposable-job mutation tasks (real AWS)
    "admin_setup": "evals.tasks.admin_setup",  # admin/onboarding tasks (mocked AWS / AwsInABox)
}

# Suites that run against the AwsInABox mock rather than real AWS.
MOCK_SUITES = {"admin_setup"}


def _load_suite(suite: str) -> list[Task]:
    mod = importlib.import_module(SUITE_MODULES[suite])
    return mod.make_tasks()


def _all_suite_tasks() -> dict[str, Task]:
    """All tasks from all suites, keyed by task id (for --task selection)."""
    out: dict[str, Task] = {}
    for suite in SUITE_MODULES:
        for t in _load_suite(suite):
            out[t.id] = t
    return out

# Build variants: name -> env overrides injected into the agent's subprocess.
VARIANTS = {
    "baseline": {},
    "revised": {"PYTHONPATH": str(VARIANT_DIR), "DEADLINE_EVALS_HELP": "revised"},
}


def load_task(name: str) -> Task:
    mod = importlib.import_module(TASK_MODULES[name])
    return Task(
        id=name,
        prompt=mod.PROMPT if hasattr(mod, "PROMPT") else "",
        allowed_tools=["Read", "Edit", "Write", "Bash"],
        setup=mod.setup,
        assertion=mod.assertion,
        prepare=getattr(mod, "prepare", None),
        finalize=getattr(mod, "finalize", None),
        requires_aws=name != "job_bundle_validate",
    )


@dataclass
class RunRecord:
    variant: str
    result: RunResult
    passed: bool
    detail: str


def _aws_authenticated() -> bool:
    out = subprocess.run(["deadline", "auth", "status"], capture_output=True, text=True)
    return "AUTHENTICATED" in out.stdout and "API Availability: True" in out.stdout


def _write_run_artifacts(run_dir: Path, record: RunRecord) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "result.json").write_text(
        json.dumps(
            {**record.result.telemetry_dict(), "passed": record.passed, "detail": record.detail},
            indent=2,
        )
    )
    with (run_dir / "events.jsonl").open("w") as f:
        for ev in record.result.raw_events:
            f.write(json.dumps(ev) + "\n")


def run_one(task: Task, variant: str, env_overrides: dict, run_idx: int, run_dir: Path) -> RunRecord:
    ctx: dict = {"run_idx": run_idx, "variant": variant}
    result = RunResult(success=False, subtype="harness_error")
    try:
        # prepare() runs BEFORE the agent (e.g. seed a failing job). No sandbox yet.
        if task.prepare is not None:
            task.prepare(ctx)

        with env.provision(task.id, lambda wd: task.setup(wd, ctx), snapshot_to=run_dir / "workspace") as workdir:
            prompt = ctx.get("prompt", task.prompt)  # setup() may override the prompt
            run_env = dict(env_overrides or {})
            if task.uses_mock:  # point the agent's aws CLI at AwsInABox
                from . import mock_aws
                run_env.update(mock_aws.agent_env())
            result = run_claude_code(
                prompt=prompt,
                workdir=workdir,
                allowed_tools=task.allowed_tools,
                mcp_config=task.mcp_config,
                max_turns=task.max_turns,
                env_overrides=run_env or None,
                model=task.model,
            )
            # finalize() runs AFTER the agent (e.g. submit authored bundle + wait).
            if task.finalize is not None:
                task.finalize(result, ctx)
            passed, detail = scorer.adjudicate_ctx(task, result, ctx)
    except Exception as e:  # one task's error must not abort the suite
        passed, detail = False, f"harness error: {type(e).__name__}: {e}"

    record = RunRecord(variant, result, passed, detail)
    _write_run_artifacts(run_dir, record)
    mark = "PASS" if passed else "FAIL"
    print(
        f"  [{task.id}/{variant}] run {run_idx}: {mark} "
        f"(tools={result.tool_call_count}, turns={result.num_turns}, "
        f"cost=${result.total_cost_usd:.4f}) -- {detail}"
    )
    return record


def run_task(task: Task, variants: list[str], k: int, autodraft_on: bool, run_root: Path) -> dict:
    """Run one task across variants, write artifacts/summary/report, return summary."""
    run_root.mkdir(parents=True, exist_ok=True)
    print(f"\n=== task={task.id}, variants={variants}, k={k} ===")
    print(f"artifacts -> {run_root}")

    # Resolve env overrides per variant. 'autodrafted' is filled in after baseline runs.
    variant_env: dict[str, dict] = {}
    for v in variants:
        if v == "autodrafted":
            variant_env[v] = {}  # populated post-baseline
        else:
            variant_env[v] = dict(VARIANTS[v])

    draft_error: str | None = None
    per_variant: dict[str, list[RunRecord]] = {}
    for variant in variants:
        # Autodraft: after baseline completes, draft revisions from its first run.
        if variant == "autodrafted" and autodraft_on:
            baseline_run1 = run_root / "baseline" / "run-1"
            drafted_path = run_root / "autodrafted.json"
            print("\n[autodraft] drafting improved docstrings from baseline run-1 ...")
            try:
                drafted = autodraft.draft(baseline_run1, drafted_path)
            except autodraft.DraftError as e:
                # Do NOT run a phantom autodrafted variant identical to baseline --
                # that would attribute model variance to docstring changes.
                draft_error = str(e)
                print(f"[autodraft] SKIPPED: {draft_error}")
                continue
            cmds = list(drafted.get("autodrafted", {}))
            print(f"[autodraft] drafted revisions for {len(cmds)} command(s) "
                  f"({', '.join(cmds)}) -> {drafted_path}")
            variant_env["autodrafted"] = {
                "PYTHONPATH": str(VARIANT_DIR),
                "DEADLINE_EVALS_HELP": "autodrafted",
                "DEADLINE_EVALS_REVISIONS_FILE": str(drafted_path),
            }

        env_overrides = variant_env[variant]
        records: list[RunRecord] = []
        for i in range(1, k + 1):
            run_dir = run_root / variant / f"run-{i}"
            records.append(run_one(task, variant, env_overrides, i, run_dir))
        per_variant[variant] = records

    # Aggregate per variant (only those that actually ran).
    stats = {v: scorer.aggregate([r.result for r in recs]) for v, recs in per_variant.items()}
    for v, s in stats.items():
        print(
            f"\n[{v}] success={s.success_rate:.0%}  cost=${s.median_cost_usd:.4f}  "
            f"tools={s.median_tool_calls:g}  turns={s.median_turns:g}  (n={s.n})"
        )
    if draft_error:
        print(f"\n[autodraft] no candidate variant ran -- drafting failed: {draft_error}")

    # Paired gate: the candidate variant must not regress vs baseline.
    candidate = next((v for v in variants if v != "baseline"), None)
    gate = None
    if "baseline" in stats and candidate in stats:
        gate = scorer.paired_gate(stats["baseline"], stats[candidate], task.thresholds)
        print(f"\nPaired gate ({candidate} vs baseline): {'PASS' if gate.passed else 'FAIL'}")
        for reason in gate.reasons:
            print(f"  - {reason}")

    # Recommendations: where did the agent struggle, and which docstrings to improve.
    recommendations = recommend.suggest(task.id, per_variant, stats)

    summary = {
        "task_id": task.id,
        "timestamp": run_root.name,
        "prompt": task.prompt,
        "model": task.model or "default",
        "k": k,
        "variants": list(stats),  # variants that actually ran
        "requested_variants": variants,
        "draft_error": draft_error,
        "aggregate": {
            v: {
                "success_rate": s.success_rate,
                "median_cost_usd": s.median_cost_usd,
                "median_tool_calls": s.median_tool_calls,
                "median_turns": s.median_turns,
                "n": s.n,
            }
            for v, s in stats.items()
        },
        "gate": None if gate is None else {"passed": gate.passed, "reasons": gate.reasons},
        "recommendations": recommendations,
        "runs": {
            v: [
                {**r.result.telemetry_dict(), "passed": r.passed, "detail": r.detail, "run": i + 1}
                for i, r in enumerate(recs)
            ]
            for v, recs in per_variant.items()
        },
    }
    (run_root / "summary.json").write_text(json.dumps(summary, indent=2))
    report.render(summary, run_root / "report.html")

    # Emit a PR-ready proposal ONLY when autodraft produced real revisions AND the
    # candidate measurably improved past the gate. An empty/failed draft or a
    # no-improvement result must not yield a misleading proposal.
    if autodraft_on and not draft_error and gate is not None and gate.passed:
        drafted_path = run_root / "autodrafted.json"
        drafted = json.loads(drafted_path.read_text()) if drafted_path.exists() else {}
        ev = recommendations.get("evidence", {})
        improved = (ev.get("tool_delta", 0) < 0 or ev.get("turn_delta", 0) < 0
                    or ev.get("success_delta", 0) > 0)
        if drafted.get("autodrafted") and improved:
            proposal = patchgen.emit_proposal(drafted, ev, run_root / "proposal.md")
            print(f"proposal -> {proposal}")
        else:
            print("[proposal] skipped: no real revisions or no measured improvement.")

    print(f"summary  -> {run_root / 'summary.json'}")
    print(f"report   -> {run_root / 'report.html'}")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deadline-evals")
    all_tasks = {**{k: None for k in TASK_MODULES}, **_all_suite_tasks()}
    ap.add_argument("--task", choices=sorted(all_tasks), help="run a single task by id")
    ap.add_argument("--suite", choices=sorted(SUITE_MODULES), help="run a whole suite")
    ap.add_argument("--suite-file", help="run a JSON eval-suite file (array of test cases)")
    ap.add_argument("--model", help="model alias/id applied to all tasks (overrides per-task)")
    ap.add_argument("--k", type=int, default=2, help="runs per variant")
    ap.add_argument("--variants", default="baseline,revised",
                    help="comma-separated subset of: " + ",".join(VARIANTS))
    ap.add_argument("--autodraft", action="store_true",
                    help="baseline -> LLM-draft docstrings -> A/B test 'autodrafted'")
    args = ap.parse_args(argv)

    if not args.task and not args.suite and not args.suite_file:
        ap.error("provide --task <id>, --suite <name>, or --suite-file <path>")

    variants = ["baseline", "autodrafted"] if args.autodraft else [
        v.strip() for v in args.variants.split(",") if v.strip()
    ]

    # Resolve the task list.
    if args.suite_file:
        from . import suite_spec
        tasks = suite_spec.load_suite_file(
            args.suite_file,
            resolve_ref=lambda n: load_task(n) if n in TASK_MODULES else _all_suite_tasks()[n],
            resolve_ref_suite=_load_suite,
        )
        group = Path(args.suite_file).stem
    elif args.suite:
        tasks = _load_suite(args.suite)
        group = args.suite
    elif args.task in TASK_MODULES:
        tasks = [load_task(args.task)]
        group = args.task
    else:
        tasks = [_all_suite_tasks()[args.task]]
        group = args.task

    # A global --model overrides every task's model.
    if args.model:
        from . import suite_spec
        m = suite_spec.resolve_model(args.model)
        for t in tasks:
            t.model = m

    if any(t.requires_aws for t in tasks) and not _aws_authenticated():
        print("ERROR: task requires AWS but `deadline auth status` is not AUTHENTICATED.")
        print("Run `deadline auth login` and retry.")
        return 2

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suite_root = OUTPUT_ROOT / group / timestamp

    def _run_all() -> int:
        summaries = []
        for task in tasks:
            run_root = suite_root / task.id if len(tasks) > 1 else suite_root
            summaries.append(run_task(task, variants, args.k, args.autodraft, run_root))

        if len(summaries) > 1:
            print(f"\n{'=' * 56}\nSUITE ROLL-UP: {group} ({len(summaries)} tasks)\n{'=' * 56}")
            for s in summaries:
                line = "  ".join(
                    f"{v}={s['aggregate'][v]['success_rate']:.0%}/{s['aggregate'][v]['median_tool_calls']:g}t"
                    for v in s["variants"] if v in s["aggregate"]
                )
                print(f"  {s['task_id']:<32} [{s.get('model','default')}]  {line}")
            (suite_root / "suite_summary.json").write_text(json.dumps(summaries, indent=2))
            report.render_suite(summaries, group, suite_root / "report.html")
            print(f"\nsuite summary -> {suite_root / 'suite_summary.json'}")
            print(f"suite report  -> {suite_root / 'report.html'}")
        return 0

    # Mock-backed tasks: ensure an AwsInABox server is up for the run. If we start
    # one, it's torn down on exit; an operator-managed server is left untouched.
    if any(t.uses_mock for t in tasks):
        from . import mock_aws
        with mock_aws.managed_server() as ready:
            if not ready:
                print(f"ERROR: AwsInABox mock not reachable at {mock_aws.ENDPOINT} and could "
                      f"not be started (binary: {mock_aws.SERVER_BIN}).")
                print("Build it (cargo build --workspace in the AWSInABox workspace) or set "
                      "DEADLINE_EVALS_AWSINABOX_BIN, then retry.")
                return 3
            print(f"[mock] AwsInABox ready at {mock_aws.ENDPOINT}")
            return _run_all()

    return _run_all()


if __name__ == "__main__":
    sys.exit(main())
