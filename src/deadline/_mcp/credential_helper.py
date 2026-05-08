# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Local credential helper for the remote MCP server.

Runs a lightweight HTTP server on localhost that serves the user's current
AWS credentials from their Deadline Cloud configuration. The remote MCP
server's OAuth authorize page fetches from this to obtain per-user credentials.

Usage:
    deadline mcp credential-helper [--port 29432]

The helper reads credentials from ~/.deadline/config (same source as CTDX/DCM)
and serves them via HTTP on localhost only. It exits when the MCP server
no longer needs credentials (or after a timeout).
"""

import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_PORT = 29432
ALLOWED_ORIGINS = [
    "https://5grpve61a5.execute-api.us-west-2.amazonaws.com",
    "null",  # For local file:// pages
]


class CredentialHandler(BaseHTTPRequestHandler):
    """HTTP handler that serves AWS credentials from the local Deadline Cloud config."""

    server: "CredentialHelperServer"

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        origin = self.headers.get("Origin", "")
        self.send_response(204)
        self._set_cors_headers(origin)
        self.end_headers()

    def do_GET(self):
        """Serve credentials on GET /credentials."""
        origin = self.headers.get("Origin", "")

        if self.path != "/credentials":
            self.send_response(404)
            self.end_headers()
            return

        try:
            creds = self._get_credentials()
            if creds is None:
                self.send_response(503)
                self._set_cors_headers(origin)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "No credentials available"}).encode())
                return

            self.send_response(200)
            self._set_cors_headers(origin)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(creds).encode())
        except Exception as e:
            logger.error(f"Error serving credentials: {e}")
            self.send_response(500)
            self.end_headers()

    def _get_credentials(self) -> Optional[dict]:
        """Read credentials from the Deadline Cloud config/profile."""
        from ..client.api._session import get_boto3_session

        try:
            session = get_boto3_session(force_refresh=True)
            credentials = session.get_credentials()
            if credentials is None:
                return None

            frozen = credentials.get_frozen_credentials()
            if frozen.access_key is None:
                return None

            return {
                "accessKeyId": frozen.access_key,
                "secretAccessKey": frozen.secret_key,
                "sessionToken": frozen.token,
                "region": session.region_name or "us-west-2",
            }
        except Exception as e:
            logger.error(f"Failed to get credentials: {e}")
            return None

    def _set_cors_headers(self, origin: str):
        """Set CORS headers to allow the MCP server's domain."""
        # Allow any HTTPS origin (the MCP server's API Gateway domain)
        if origin.startswith("https://") or origin == "null":
            self.send_header("Access-Control-Allow-Origin", origin)
        else:
            self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGINS[0])
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "3600")

    def log_message(self, format, *args):
        """Suppress default HTTP server logging."""
        logger.debug(format % args)


class CredentialHelperServer:
    """Localhost-only HTTP server that serves AWS credentials."""

    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start the credential helper server."""
        self._server = HTTPServer(("127.0.0.1", self.port), CredentialHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(f"Credential helper listening on http://127.0.0.1:{self.port}")

    def stop(self):
        """Stop the server."""
        if self._server:
            self._server.shutdown()
            self._server = None

    def run_forever(self):
        """Run in the foreground (blocking)."""
        self._server = HTTPServer(("127.0.0.1", self.port), CredentialHandler)
        logger.info(f"Credential helper listening on http://127.0.0.1:{self.port}")
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self._server.shutdown()


def main(port: int = DEFAULT_PORT):
    """Run the credential helper as a standalone process."""
    import sys

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    server = CredentialHelperServer(port=port)
    print(f"Deadline Cloud credential helper running on http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop")
    server.run_forever()
