# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

from mcp.server.fastmcp import FastMCP

from .utils import register_api_tools

INSTRUCTIONS = """
# AWS Deadline Cloud MCP Server

This server provides tools for interacting with AWS Deadline Cloud render farm management service.

## Debugging Failed Jobs Workflow

When debugging failed Deadline Cloud jobs, follow this sequence:

1. **Find failed jobs**: Use `deadline_search_jobs` with `task_run_status="FAILED"` to find jobs in a failed state
2. **Get job details**: Use `deadline_get_job` to get full job info including taskRunStatusCounts
3. **List steps**: Use `deadline_list_steps` to identify which steps failed (look for FAILED in taskRunStatusCounts)
4. **List tasks**: Use `deadline_list_tasks` for the failed step to find specific failed task IDs
5. **List sessions**: Use `deadline_list_sessions` to get session IDs for the job
6. **Get logs**: Use `deadline_get_session_and_worker_logs` with the session_id — this fetches session details, session logs (task stdout/stderr), AND worker logs (infrastructure events) in one call, with correct worker-session pairing. If worker logs return a permissions error, fall back to `deadline_get_session_logs` for session logs only.

**CRITICAL**: Worker logs show WHY a task was killed — spot interruptions, instance termination, agent crashes, OOM kills, etc. Session logs alone cannot determine the root cause of cancelled or interrupted tasks. The `deadline_get_session_and_worker_logs` tool always returns both.

## Common Root Causes Only Visible in Worker Logs

- **Spot interruption**: Look for "Shutting down the host", "Received signal 15", or EC2 termination notices
- **Worker shutdown**: Status changes to STOPPING, shutdown signals
- **Agent crash**: Errors in worker agent before task failure
- **Environment setup failure**: Issues loading environments or dependencies
- **Resource exhaustion**: Memory, disk, or system limit errors

When session logs show SIGTERM (exit code -15) or unexplained cancellation, the worker logs will contain the actual reason.

## AWS CLI Fallback

If no logs are returned, logs may be at a different position. Use `--start-from-head`:
```
aws logs get-log-events --log-group-name "/aws/deadline/{farm_id}/{queue_id}" --log-stream-name "{session_id}" --start-from-head --limit 100
```

For worker logs:
```
aws logs get-log-events --log-group-name "/aws/deadline/{farm_id}/{fleet_id}" --log-stream-name "{worker_id}" --start-from-head --limit 100
```

## Key Concepts

- **Farm**: Top-level resource containing queues and fleets
- **Queue**: Where jobs are submitted and scheduled
- **Fleet**: A group of workers that can process jobs (may use EC2 spot instances)
- **Worker**: A compute instance that runs job tasks
- **Job**: A unit of work containing steps and tasks
- **Step**: A stage within a job (e.g., render, composite)
- **Task**: Individual work item within a step
- **Session**: Worker execution context with associated logs

## Configuration

This server uses the Deadline Cloud configuration from `~/.deadline/config`, NOT the standard AWS credential chain. The config file specifies:
- `defaults.aws_profile_name`: The AWS profile used for all API calls (e.g., a Deadline Cloud Monitor profile)
- `defaults.farm_id`: Default farm ID
- `defaults.queue_id`: Default queue ID

When asked about authentication or which profile/credentials are being used, refer to the Deadline Cloud config file (`~/.deadline/config`) and the `aws_profile_name` setting, not the standard AWS credential chain.
"""

import os

_transport_security = None
if os.environ.get("MCP_TRANSPORT") == "streamable-http":
    from mcp.server.transport_security import TransportSecuritySettings

    _transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

app = FastMCP(
    "deadline-cloud",
    instructions=INSTRUCTIONS,
    transport_security=_transport_security,
)

register_api_tools(app, prefix="deadline_")


def main(
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    auth_mode: str = "local",
):
    """Start the MCP server with the specified transport and auth configuration.

    Args:
        transport: 'stdio' for local clients, 'streamable-http' for remote hosting.
        host: Bind address for HTTP transport.
        port: Bind port for HTTP transport.
        auth_mode: 'local' uses ~/.deadline/config, 'oauth-delegation' for remote per-user auth.
    """
    if auth_mode == "oauth-delegation":
        _configure_oauth_delegation()

    if transport == "stdio":
        app.run()
    elif transport == "streamable-http":
        if auth_mode == "oauth-delegation":
            _run_with_oauth_middleware(host, port)
        else:
            app.settings.host = host
            app.settings.port = port
            app.run(transport="streamable-http")


def _configure_oauth_delegation():
    """Configure the server for OAuth-based credential delegation.

    Installs the middleware that patches boto3 session creation to use
    per-request delegated credentials.
    """
    import os
    import logging

    logger = logging.getLogger(__name__)

    required_vars = ["IDC_ISSUER_URL", "DELEGATION_ROLE_ARN"]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        logger.warning(
            f"OAuth delegation mode requires environment variables: {missing}. "
            "Falling back to local credential mode."
        )
        return

    from .middleware import install_delegation_middleware

    install_delegation_middleware()

    logger.info(
        "MCP server configured for OAuth credential delegation. "
        f"Issuer: {os.environ['IDC_ISSUER_URL']}"
    )


def _run_with_oauth_middleware(host: str, port: int):
    """Run the MCP server with an ASGI wrapper that handles OAuth token extraction.

    Wraps the FastMCP streamable-http server with middleware that:
    1. Extracts Bearer tokens from the Authorization header
    2. Exchanges them for per-user AWS credentials
    3. Sets thread-local credentials before each tool invocation
    4. Returns 401 if no valid token is provided
    """
    import logging
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    from .auth import (
        AuthenticationError,
        CredentialDelegationError,
        OAuthCredentialDelegator,
        set_request_credentials,
        clear_request_credentials,
    )

    logger = logging.getLogger(__name__)
    delegator = OAuthCredentialDelegator()

    class OAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # Health check endpoint doesn't require auth
            if request.url.path == "/health":
                return JSONResponse({"status": "ok"})

            # Extract Bearer token
            auth_header = request.headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "missing_token",
                        "error_description": "Authorization header with Bearer token required",
                    },
                    headers={"WWW-Authenticate": 'Bearer realm="deadline-mcp"'},
                )

            token = auth_header[7:]  # Strip "Bearer " prefix

            try:
                creds = delegator.exchange_token(token)
                set_request_credentials(creds)
            except AuthenticationError as e:
                return JSONResponse(
                    status_code=401,
                    content={"error": "invalid_token", "error_description": str(e)},
                    headers={"WWW-Authenticate": 'Bearer realm="deadline-mcp"'},
                )
            except CredentialDelegationError as e:
                logger.error(f"Credential delegation failed: {e}")
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": "delegation_error",
                        "error_description": "Failed to obtain credentials. Please try again.",
                    },
                )

            try:
                response = await call_next(request)
                return response
            finally:
                clear_request_credentials()

    # Get the underlying ASGI app from FastMCP's streamable-http transport
    mcp_app = app.streamable_http_app()

    # Wrap with OAuth middleware
    from starlette.routing import Mount, Route

    async def health_handler(request: Request):
        return JSONResponse({"status": "ok"})

    wrapped_app = Starlette(
        routes=[
            Route("/health", health_handler, methods=["GET"]),
            Mount("/", app=mcp_app),
        ],
        middleware=[Middleware(OAuthMiddleware)],
    )

    import uvicorn

    logger.info(f"Starting MCP server with OAuth on {host}:{port}")
    uvicorn.run(wrapped_app, host=host, port=port, forwarded_allow_ips="*")
