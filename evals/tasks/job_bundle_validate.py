"""Sample OFFLINE deadline-cloud task for the POC.

The agent is asked to fix an invalid Open Job Description job bundle so that
`deadline bundle gui-submit --output` / validation would accept it. We keep it
fully offline: success is adjudicated by parsing the template the agent produces,
NOT by submitting to AWS.

This exercises the real loop (agent edits files driven by deadline-cloud domain
knowledge) without touching credentials -- the whole point of the POC.
"""

from __future__ import annotations

from pathlib import Path

# A deliberately broken OpenJD template: `template` should be `specificationVersion`,
# and the step is missing its required `script`/`actions`. The agent must repair it.
BROKEN_TEMPLATE = """\
specificationVersion: "jobtemplate-2023-09"
name: RenderJob
steps:
  - name: RenderStep
    parameterSpace:
      taskParameterDefinitions:
        - name: Frame
          type: INT
          range: "1-10"
"""

PROMPT = (
    "The file template.yaml in this directory is an Open Job Description (OpenJD) "
    "job template for AWS Deadline Cloud, but it is invalid: a step is missing its "
    "required run script. Edit template.yaml so the RenderStep has a valid "
    "`script` with an `actions.onRun` command that echoes the Frame parameter "
    "(e.g. runs `echo {{Task.Param.Frame}}`). Keep it minimal and valid OpenJD. "
    "Do not add any other steps."
)


def setup(workdir: Path, ctx: dict) -> None:
    (workdir / "template.yaml").write_text(BROKEN_TEMPLATE)


def assertion(result, ctx: dict) -> tuple[bool, str]:  # noqa: ANN001 (RunResult, avoid circ import)
    """Parse the produced template; require a valid run script on the step."""
    path = result.workdir / "template.yaml"
    if not path.exists():
        return False, "template.yaml missing after run"

    try:
        import yaml  # PyYAML
    except ImportError:
        return False, "PyYAML not installed (pip install pyyaml)"

    try:
        doc = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        return False, f"template is not valid YAML: {e}"

    steps = doc.get("steps") or []
    if len(steps) != 1:
        return False, f"expected exactly 1 step, found {len(steps)}"

    step = steps[0]
    script = step.get("script")
    if not isinstance(script, dict):
        return False, "step has no `script` mapping"

    actions = script.get("actions") or {}
    on_run = actions.get("onRun") or {}
    command = on_run.get("command")
    if not command:
        return False, "script.actions.onRun.command is missing"

    # Light semantic check: the run should reference the Frame task parameter.
    blob = str(on_run)
    if "Frame" not in blob:
        return False, "onRun does not reference the Frame parameter"

    return True, "valid OpenJD step with onRun command referencing Frame"
