#!/usr/bin/env python3
"""
HTTP Bridge for Borealis MCP

Translates between STDIO (MCP client) and HTTP (remote MCP server).
This allows MCP clients to connect to Borealis running on Aurora via SSH tunnel.

Usage:
    python http_bridge.py http://localhost:9000/mcp

Setup:
    1. Establish SSH tunnel: ssh -L 9000:localhost:9000 user@aurora.alcf.anl.gov
    2. On Aurora, start Borealis in HTTP mode: python -m borealis_mcp.server --transport http
    3. Configure MCP client to use this bridge
"""

import argparse
import json
import sys
from typing import Optional

try:
    import requests
except ImportError:
    print(
        "Error: requests library not installed. Run: pip install requests",
        file=sys.stderr,
    )
    sys.exit(1)


class HTTPBridge:
    """Bridge between STDIO and HTTP for MCP communication."""

    def __init__(self, server_url: str):
        """
        Initialize HTTP bridge.

        Args:
            server_url: URL of the HTTP MCP server (e.g., http://localhost:9000/mcp)
        """
        self.server_url = server_url.rstrip("/")
        self.session = requests.Session()
        self.session_id: Optional[str] = None

        # Ensure server is reachable
        self._check_server()

    def _check_server(self) -> None:
        """Check if server is reachable."""
        try:
            response = self.session.get(f"{self.server_url}/health", timeout=5)
            response.raise_for_status()
            print(f"Connected to MCP server at {self.server_url}", file=sys.stderr)
        except requests.exceptions.RequestException as e:
            print(
                f"Warning: Health check failed for {self.server_url}",
                file=sys.stderr,
            )
            print(f"Details: {e}", file=sys.stderr)
            print("Continuing anyway - server may not support /health endpoint", file=sys.stderr)

    def send_request(self, request: dict) -> dict:
        """
        Send JSON-RPC request to HTTP server.

        Args:
            request: JSON-RPC request object

        Returns:
            JSON-RPC response object
        """
        try:
            # Add session ID if we have one
            headers = {"Content-Type": "application/json"}
            if self.session_id:
                headers["X-Session-ID"] = self.session_id

            response = self.session.post(
                f"{self.server_url}/messages",
                json=request,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()

            # Extract session ID from response if provided
            if "X-Session-ID" in response.headers:
                self.session_id = response.headers["X-Session-ID"]

            return response.json()

        except requests.exceptions.RequestException as e:
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {"code": -32000, "message": f"HTTP request failed: {str(e)}"},
            }

    def run(self) -> None:
        """
        Main loop: read from stdin, send to HTTP server, write response to stdout.
        """
        print("HTTP Bridge started", file=sys.stderr)
        print(f"Server URL: {self.server_url}", file=sys.stderr)
        print("Waiting for MCP messages on stdin...", file=sys.stderr)

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                # Parse JSON-RPC request from stdin
                request = json.loads(line)

                # Send to HTTP server
                response = self.send_request(request)

                # Write response to stdout
                print(json.dumps(response), flush=True)

            except json.JSONDecodeError as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {str(e)}"},
                }
                print(json.dumps(error_response), flush=True)

            except Exception as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32603, "message": f"Internal error: {str(e)}"},
                }
                print(json.dumps(error_response), flush=True)


def main() -> None:
    """Entry point for the HTTP bridge."""
    parser = argparse.ArgumentParser(
        description="HTTP bridge for MCP STDIO to HTTP translation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s http://localhost:9000/mcp
  %(prog)s http://127.0.0.1:9000/mcp

Setup for ALCF systems:
  1. SSH to Aurora with tunnel:
     ssh -L 9000:localhost:9000 username@aurora.alcf.anl.gov

  2. On Aurora, start the MCP server:
     python -m borealis_mcp.server --transport http --port 9000

  3. Configure your MCP client to use this bridge
""",
    )
    parser.add_argument(
        "server_url",
        help="URL of the HTTP MCP server (e.g., http://localhost:9000/mcp)",
    )
    args = parser.parse_args()

    bridge = HTTPBridge(args.server_url)
    bridge.run()


if __name__ == "__main__":
    main()
