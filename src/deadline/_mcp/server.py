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

from mcp.server.transport_security import TransportSecuritySettings


def _create_app(auth_mode: str = "local", host: str = "127.0.0.1", port: int = 8000):
    """Create the FastMCP app with appropriate auth and transport settings."""
    kwargs = {
        "instructions": INSTRUCTIONS,
        "host": host,
        "port": port,
    }

    # Disable DNS rebinding protection when running behind a proxy
    if os.environ.get("MCP_TRANSPORT") == "streamable-http" or auth_mode == "oauth-delegation":
        kwargs["transport_security"] = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )

    # Wire up OAuth provider for credential delegation mode
    if auth_mode == "oauth-delegation":
        from mcp.server.auth.settings import ClientRegistrationOptions
        from mcp.server.fastmcp.server import AuthSettings
        from .oauth_provider import AwsSignInOAuthProvider

        server_url = os.environ.get(
            "MCP_SERVER_URL", "https://5grpve61a5.execute-api.us-west-2.amazonaws.com"
        )

        oauth_provider = AwsSignInOAuthProvider()

        kwargs["auth_server_provider"] = oauth_provider
        kwargs["auth"] = AuthSettings(
            issuer_url=server_url,
            resource_server_url=server_url,
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["deadline:read", "deadline:write"],
            ),
        )

    mcp_app = FastMCP("deadline-cloud", **kwargs)

    # Clear registration flags so tools can be re-registered on this new app instance
    from .registry import get_all_tool_names, get_tool_definition

    for tool_name in get_all_tool_names():
        func = get_tool_definition(tool_name)["func"]
        if hasattr(func, "_mcp_tool_registered"):
            del func._mcp_tool_registered

    register_api_tools(mcp_app, prefix="deadline_")
    return mcp_app


# Module-level app for stdio mode (backwards compatible)
app = _create_app()


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
    global app

    if auth_mode == "oauth-delegation":
        # Recreate app with OAuth provider
        app = _create_app(auth_mode=auth_mode, host=host, port=port)
        from .middleware import install_delegation_middleware

        install_delegation_middleware()

    if transport == "stdio":
        app.run()
    elif transport == "streamable-http":
        app.settings.host = host
        app.settings.port = port

        if auth_mode == "oauth-delegation":
            _run_with_callback_route(app, host, port)
        else:
            app.run(transport="streamable-http")


def _run_with_callback_route(mcp_app, host: str, port: int):
    """Run the server with an additional /oauth/callback route for AWS Sign-In."""
    import anyio
    import uvicorn
    from starlette.requests import Request
    from starlette.responses import HTMLResponse, RedirectResponse
    from starlette.routing import Route

    from .oauth_provider import AwsSignInOAuthProvider

    # Get the OAuth provider instance from the app
    oauth_provider = mcp_app._auth_server_provider

    async def aws_callback(request: Request):
        """Handle AWS Sign-In redirect after user authenticates."""
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        error = request.query_params.get("error")

        if error:
            return HTMLResponse(
                f"<h1>Authentication Failed</h1><p>{error}: {request.query_params.get('error_description', '')}</p>",
                status_code=400,
            )

        if not code or not state:
            return HTMLResponse("<h1>Missing parameters</h1>", status_code=400)

        try:
            redirect_url = await oauth_provider.handle_aws_callback(code, state)
            return RedirectResponse(redirect_url)
        except Exception as e:
            return HTMLResponse(
                f"<h1>Authentication Error</h1><p>{e}</p>", status_code=500
            )

    # Get the base Starlette app and add our callback route
    starlette_app = mcp_app.streamable_http_app()
    starlette_app.routes.append(Route("/oauth/callback", aws_callback, methods=["GET"]))

    config = uvicorn.Config(starlette_app, host=host, port=port, forwarded_allow_ips="*")
    server = uvicorn.Server(config)

    async def serve():
        await server.serve()

    anyio.run(serve)


