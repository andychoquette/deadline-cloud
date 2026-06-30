# deadline-evals (local POC)

A working proof-of-concept of the eval loop: drive **Claude Code** headless against
a deadline-cloud task, capture telemetry, adjudicate success programmatically, and
apply a paired telemetry-regression gate. **Fully offline — no AWS, no credentials.**

## Run it

```bash
python -m evals.runner --task job_bundle_validate --k 2 --self-compare
```

Requires the `claude` CLI on PATH (ASBX/Cecelia wrapper is fine) and `pyyaml`.

## What the POC proves

- **Headless invocation + telemetry from one stream.** `claude -p --output-format
  stream-json --verbose` emits per-`tool_use` events *and* a final `result` event
  carrying `usage`, `total_cost_usd`, `num_turns`, `is_error`. No OTLP collector
  needed for the gate's metrics. (See `harness.py`.)
- **Tool restriction, non-interactive.** `--allowedTools ... --permission-mode
  bypassPermissions --max-turns N` runs without approval prompts.
- **Programmatic adjudication.** The task ships its own assertion (parse the OpenJD
  template the agent produced); the agent's run is graded by inspecting sandbox state.
- **Paired telemetry gate.** `scorer.paired_gate` fails on success regression OR a
  cost/tool-call/turn median delta beyond per-task thresholds (default 30%).

## Module map (mirrors the design doc boundaries)

| File | Role | Design doc |
|------|------|-----------|
| `harness.py` | drive Claude Code, parse telemetry | 4.2 HarnessAdapter seam |
| `task.py` | task definition (prompt + setup + assertion + thresholds) | 4.3 core artifact |
| `env.py` | isolated sandbox provision/teardown | 4.5 (AWS farm later) |
| `scorer.py` | adjudication + paired telemetry gate | 4.4 / 4.10 |
| `runner.py` | the loop: K-run sampling, aggregate, report | 4.2 |
| `tasks/` | sample offline deadline-cloud tasks | 4.3 |

## Deliberately NOT in the POC (next steps)

- **Second build + BuildSource.** Install a baseline ref and a candidate ref into
  per-run venvs and run the *real* paired comparison (`scorer.paired_gate` is ready).
- **Real-AWS tasks.** Ephemeral run-id-tagged farm + reaper behind `env.provision`.
- **MCP injection.** `--mcp-config` is wired in `harness.py` but no server is attached yet.
- **CI workflow.** `eval_gate.yml` (dispatch/call-only + OIDC) — gated on the
  credential decisions still open in the design doc.

## Observed cost note

Each run of the sample task ~= $0.30 and 3 turns. K-run sampling × 2 builds × N
tasks multiplies this — a real input for the "how big is the suite / how high is K"
budgeting discussed in the design doc.
