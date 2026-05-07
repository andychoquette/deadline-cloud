# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
The `deadline mcp-server` command.
"""

import sys
import click

from .._common import _handle_error
from .._main import deadline as main
from ...api._telemetry import get_deadline_cloud_library_telemetry_client


@main.command(name="mcp-server")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "streamable-http"]),
    default="stdio",
    help="Transport protocol. Use 'stdio' for local MCP clients, 'streamable-http' for remote hosting.",
)
@click.option(
    "--host",
    default="127.0.0.1",
    help="Host to bind to when using streamable-http transport.",
)
@click.option(
    "--port",
    default=8000,
    type=int,
    help="Port to bind to when using streamable-http transport.",
)
@click.option(
    "--auth-mode",
    type=click.Choice(["local", "oauth-delegation"]),
    default="local",
    help="Authentication mode. 'local' uses ~/.deadline/config, 'oauth-delegation' validates OAuth tokens and assumes per-user roles.",
)
@_handle_error
def cli_mcp_server(transport: str, host: str, port: int, auth_mode: str):
    """
    EXPERIMENTAL - Start the AWS Deadline Cloud MCP (Model Context Protocol) server.

    The MCP server provides LLM tools with access to AWS Deadline Cloud operations
    through the Model Context Protocol. This allows AI assistants to interact with
    Deadline Cloud services on your behalf.

    The server will run until interrupted with Ctrl+C or Ctrl+D.

    For local use (default):
        deadline mcp-server

    For remote hosting:
        deadline mcp-server --transport streamable-http --host 0.0.0.0 --port 8000

    Note: This command requires MCP dependencies. Install them with:
    pip install 'deadline[mcp]'
    """
    try:
        from ...._mcp.server import main as mcp_main
    except ImportError:
        click.echo(
            "Error: MCP dependencies not installed.\n"
            "Please install them with: pip install 'deadline[mcp]'",
            err=True,
        )
        sys.exit(1)

    # Record server startup telemetry
    try:
        telemetry_client = get_deadline_cloud_library_telemetry_client()
        telemetry_client.record_event(
            event_type="com.amazon.rum.deadline.mcp.server_startup",
            event_details={
                "usage_mode": "MCP",
                "startup_method": "cli",
                "transport": transport,
                "auth_mode": auth_mode,
            },
        )
    except Exception:
        pass

    mcp_main(transport=transport, host=host, port=port, auth_mode=auth_mode)
