#!/bin/bash
# Start Borealis MCP server in HTTP mode as a background daemon
#
# Usage:
#   ./start_borealis_daemon.sh [options]
#
# Options:
#   --system SYSTEM    System name (aurora, polaris, sunspot). Default: auto-detect
#   --port PORT        Port to bind to. Default: 9000
#   --host HOST        Host to bind to. Default: 0.0.0.0
#   --stop             Stop the running daemon
#   --status           Check daemon status
#   --help             Show this help message
#
# The daemon writes its PID and connection info to:
#   ~/.borealis/daemon.info
#
# Logs are written to:
#   ~/.borealis/daemon.log

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOREALIS_DIR="$HOME/.borealis"
PID_FILE="$BOREALIS_DIR/daemon.pid"
INFO_FILE="$BOREALIS_DIR/daemon.info"
LOG_FILE="$BOREALIS_DIR/daemon.log"

# Default values
SYSTEM=""
PORT=9000
HOST="0.0.0.0"
ACTION="start"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --system)
            SYSTEM="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        --stop)
            ACTION="stop"
            shift
            ;;
        --status)
            ACTION="status"
            shift
            ;;
        --help|-h)
            head -25 "$0" | tail -23
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Ensure borealis directory exists
mkdir -p "$BOREALIS_DIR"

stop_daemon() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "Stopping Borealis MCP daemon (PID: $PID)..."
            kill "$PID"
            sleep 1
            if kill -0 "$PID" 2>/dev/null; then
                echo "Process still running, sending SIGKILL..."
                kill -9 "$PID" 2>/dev/null || true
            fi
            echo "Daemon stopped."
        else
            echo "PID $PID not running (stale PID file)."
        fi
        rm -f "$PID_FILE"
        rm -f "$INFO_FILE"
    else
        echo "No PID file found. Daemon may not be running."
    fi
}

check_status() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "Borealis MCP daemon is RUNNING"
            echo ""
            if [ -f "$INFO_FILE" ]; then
                cat "$INFO_FILE"
            fi
            return 0
        else
            echo "Borealis MCP daemon is NOT RUNNING (stale PID file)"
            return 1
        fi
    else
        echo "Borealis MCP daemon is NOT RUNNING"
        return 1
    fi
}

start_daemon() {
    # Check if already running
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "Borealis MCP daemon is already running (PID: $PID)"
            echo "Use --stop to stop it first, or --status to check."
            exit 1
        else
            echo "Removing stale PID file..."
            rm -f "$PID_FILE"
        fi
    fi

    # Activate virtual environment if it exists
    if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
        source "$SCRIPT_DIR/venv/bin/activate"
    fi

    # Add pbs-python-api to PYTHONPATH if using the bundled version
    if [ -d "$SCRIPT_DIR/external/pbs-python-api" ]; then
        export PYTHONPATH="$SCRIPT_DIR/external/pbs-python-api:$PYTHONPATH"
    fi

    # Add system PBS Python bindings path (required on ALCF systems)
    export PYTHONPATH="$PYTHONPATH:/opt/pbs/lib/python/altair"

    # Auto-detect system if not specified
    if [ -z "$SYSTEM" ]; then
        HOSTNAME=$(hostname)
        case "$HOSTNAME" in
            *aurora*|uan*)
                SYSTEM="aurora"
                ;;
            *polaris*)
                SYSTEM="polaris"
                ;;
            *sunspot*)
                SYSTEM="sunspot"
                ;;
            *)
                SYSTEM="aurora"  # Default
                ;;
        esac
    fi

    # Configure PBS environment based on system
    case "$SYSTEM" in
        aurora)
            export PBS_SERVER="aurora-pbs-0001.hostmgmt.cm.aurora.alcf.anl.gov"
            export PBS_ACCOUNT="${PBS_ACCOUNT:-datascience}"
            export BOREALIS_SYSTEM="aurora"
            ;;
        polaris)
            export PBS_SERVER="polaris-pbs-01.hsn.cm.polaris.alcf.anl.gov"
            export PBS_ACCOUNT="${PBS_ACCOUNT:-datascience}"
            export BOREALIS_SYSTEM="polaris"
            ;;
        sunspot)
            export PBS_SERVER="sunspot-pbs-01.sunspot.alcf.anl.gov"
            export PBS_ACCOUNT="${PBS_ACCOUNT:-datascience}"
            export BOREALIS_SYSTEM="sunspot"
            ;;
        *)
            echo "Unknown system: $SYSTEM"
            exit 1
            ;;
    esac

    # Get hostname for connection info
    FULL_HOSTNAME=$(hostname -f 2>/dev/null || hostname)

    echo "Starting Borealis MCP daemon..."
    echo "  System:     $SYSTEM"
    echo "  Host:       $HOST:$PORT"
    echo "  Hostname:   $FULL_HOSTNAME"
    echo "  Log file:   $LOG_FILE"

    # Start the server in the background
    nohup python -m borealis_mcp.server \
        --transport http \
        --host "$HOST" \
        --port "$PORT" \
        --system "$SYSTEM" \
        >> "$LOG_FILE" 2>&1 &

    DAEMON_PID=$!
    echo "$DAEMON_PID" > "$PID_FILE"

    # Wait briefly to check if it started successfully
    sleep 2
    if ! kill -0 "$DAEMON_PID" 2>/dev/null; then
        echo ""
        echo "ERROR: Daemon failed to start. Check log file:"
        echo "  tail -50 $LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi

    # Write connection info
    cat > "$INFO_FILE" << EOF
# Borealis MCP Daemon Info
# Generated: $(date)

PID=$DAEMON_PID
HOSTNAME=$FULL_HOSTNAME
SYSTEM=$SYSTEM
PORT=$PORT
HOST=$HOST
LOG_FILE=$LOG_FILE

# MCP Endpoint URL (use from remote machine with SSH tunnel)
MCP_URL=http://localhost:$PORT/mcp

# SSH tunnel command (run on your local machine):
# ssh -L $PORT:localhost:$PORT $FULL_HOSTNAME

# Claude Code config (~/.claude.json or settings):
# {
#   "mcpServers": {
#     "pbs": {
#       "url": "http://localhost:$PORT/mcp/sse"
#     }
#   }
# }
EOF

    echo ""
    echo "Borealis MCP daemon started successfully!"
    echo ""
    echo "  PID:        $DAEMON_PID"
    echo "  Info file:  $INFO_FILE"
    echo ""
    echo "To connect from your local machine:"
    echo "  1. Create SSH tunnel:"
    echo "     ssh -L $PORT:localhost:$PORT $FULL_HOSTNAME"
    echo ""
    echo "  2. Configure Claude Code MCP:"
    echo "     URL: http://localhost:$PORT/mcp/sse"
    echo ""
    echo "To stop the daemon:"
    echo "  $0 --stop"
}

# Execute the requested action
case "$ACTION" in
    start)
        start_daemon
        ;;
    stop)
        stop_daemon
        ;;
    status)
        check_status
        ;;
esac
