"""Mocked-AWS environment support (AwsInABox).

The 3rd environment type (alongside real-aws jobs and offline authoring): admin /
onboarding tasks that create real Deadline resources, but against the local
AwsInABox emulator instead of real AWS -- so the agent issues genuine
`aws deadline create-farm/...` calls with zero real-AWS risk.

AwsInABox runs as a standalone server (its own Brazil workspace) on a port; we just
point the agent's CLI at it via AWS_ENDPOINT_URL and grade by reading resulting
state back through the same endpoint. No call-log API exists, so assertions query
List*/Get* (state-based verification, the tool's intended pattern).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ENDPOINT = os.environ.get("DEADLINE_EVALS_MOCK_ENDPOINT", "http://localhost:9297")
# AwsInABox uses a fixed account and accepts (never validates) credentials.
MOCK_REGION = "us-east-1"

# Path to the built aws-in-a-box router binary. Set via env to the
# `target/debug/aws-in-a-box` produced by `cargo build --workspace` in an
# AWSInABox checkout. Empty default => the runner's preflight reports how to set it.
SERVER_BIN = os.environ.get("DEADLINE_EVALS_AWSINABOX_BIN", "")
SERVER_SERVICES = os.environ.get("DEADLINE_EVALS_AWSINABOX_SERVICES", "deadline,s3,sts")
SERVER_PORT = ENDPOINT.rsplit(":", 1)[-1]


def agent_env() -> dict[str, str]:
    """Env overrides that point the agent's aws/deadline CLI at the mock."""
    return {
        "AWS_ENDPOINT_URL": ENDPOINT,
        "AWS_DEFAULT_REGION": MOCK_REGION,
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
    }


def is_up() -> bool:
    """Cheap liveness check: a ListFarms against the mock should answer."""
    try:
        return aws_deadline(["list-farms"]) is not None
    except Exception:
        return False


@contextmanager
def managed_server() -> Iterator[bool]:
    """Ensure an AwsInABox server is up for the duration of the block.

    Principle: only stop a server WE started. If one is already up, yield and leave
    it running (it was the operator's). If not, start one (if the binary exists),
    wait for readiness, yield, then terminate the process WE spawned on exit.

    Yields True if the mock is usable, False if it couldn't be brought up.
    """
    if is_up():
        yield True  # operator-managed; don't touch it
        return

    if not Path(SERVER_BIN).exists():
        yield False  # can't start one; caller's preflight will report the guidance
        return

    proc = subprocess.Popen(
        [SERVER_BIN],
        env={**os.environ, "PORT": SERVER_PORT, "SERVICES": SERVER_SERVICES,
             "MAX_LIFETIME_SECS": "0"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        ready = False
        for _ in range(30):  # ~15s readiness poll
            if is_up():
                ready = True
                break
            time.sleep(0.5)
        yield ready
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def aws_deadline(args: list[str]) -> dict | None:
    """Run `aws deadline <args>` against the mock and return parsed JSON (or None)."""
    env = {**os.environ, **agent_env()}
    proc = subprocess.run(
        ["aws", "deadline", *args, "--endpoint-url", ENDPOINT,
         "--region", MOCK_REGION, "--output", "json"],
        capture_output=True, text=True, env=env,
    )
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None
