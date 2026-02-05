#!/bin/bash
# Start SSH tunnel and Borealis MCP server
#
# Usage:
#   ./start_borealis_tunnel.sh [username] [borealis_path]
#
# Examples:
#   ./start_borealis_tunnel.sh
#   ./start_borealis_tunnel.sh myuser
#   ./start_borealis_tunnel.sh myuser ~/borealis-mcp

set -e

AURORA_USER="${1:-$USER}"
AURORA_HOST="aurora.alcf.anl.gov"
LOCAL_PORT=9000
BOREALIS_PATH="${2:-~/borealis-mcp}"

echo "==============================================="
echo "Borealis MCP SSH Tunnel Launcher"
echo "==============================================="
echo ""
echo "This will:"
echo "  1. Establish SSH tunnel to Aurora (requires MFA)"
echo "  2. Start Borealis MCP server in HTTP mode"
echo "  3. Keep both running until you press Ctrl+C"
echo ""
echo "Configuration:"
echo "  User:        ${AURORA_USER}"
echo "  Host:        ${AURORA_HOST}"
echo "  Local Port:  ${LOCAL_PORT}"
echo "  Remote Path: ${BOREALIS_PATH}"
echo ""
echo "After connection, configure your MCP client to use:"
echo "  python tools/http_bridge.py http://localhost:${LOCAL_PORT}/mcp"
echo ""
echo "==============================================="
echo ""
echo "Connecting... (you will be prompted for MFA)"
echo ""

# Start tunnel and server
# The SSH command will:
#   -L: Forward local port to remote localhost
#   -o ServerAliveInterval: Send keepalive every 60 seconds
#   -o ServerAliveCountMax: Disconnect after 3 missed keepalives
#   -t: Force pseudo-terminal (needed for interactive commands)
ssh -L ${LOCAL_PORT}:localhost:${LOCAL_PORT} \
    -o ServerAliveInterval=60 \
    -o ServerAliveCountMax=3 \
    -t \
    ${AURORA_USER}@${AURORA_HOST} \
    "cd ${BOREALIS_PATH} && \
     source venv/bin/activate 2>/dev/null || true && \
     export BOREALIS_SYSTEM=aurora && \
     export PBS_ACCOUNT=\${PBS_ACCOUNT:-datascience} && \
     echo 'Starting Borealis MCP on port ${LOCAL_PORT}...' && \
     python -m borealis_mcp.server --transport http --port ${LOCAL_PORT}"
