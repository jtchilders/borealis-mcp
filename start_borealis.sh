#!/bin/bash
# Start Borealis MCP server with proper PBS environment
#
# Usage:
#   source start_borealis.sh [system]
#
# Examples:
#   source start_borealis.sh           # Auto-detect or default to aurora
#   source start_borealis.sh aurora
#   source start_borealis.sh polaris
#   source start_borealis.sh sunspot
#
# This script should be sourced (not executed) to set environment variables
# in the current shell, or it can be used directly to launch the server.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEM=${1:-aurora}

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

case "$SYSTEM" in
    aurora)
        export PBS_SERVER="aurora-pbs-0001.hostmgmt.cm.aurora.alcf.anl.gov"
        export PBS_ACCOUNT="${PBS_ACCOUNT:-datascience}"
        export BOREALIS_SYSTEM="aurora"
        echo "PBS environment configured for Aurora"
        ;;
    polaris)
        export PBS_SERVER="polaris-pbs-01.hsn.cm.polaris.alcf.anl.gov"
        export PBS_ACCOUNT="${PBS_ACCOUNT:-datascience}"
        export BOREALIS_SYSTEM="polaris"
        echo "PBS environment configured for Polaris"
        ;;
    sunspot)
        export PBS_SERVER="sunspot-pbs-01.sunspot.alcf.anl.gov"
        export PBS_ACCOUNT="${PBS_ACCOUNT:-datascience}"
        export BOREALIS_SYSTEM="sunspot"
        echo "PBS environment configured for Sunspot"
        ;;
    *)
        echo "Unknown system: $SYSTEM"
        echo "Usage: source start_borealis.sh [aurora|polaris|sunspot]"
        return 1 2>/dev/null || exit 1
        ;;
esac

echo "  PBS_SERVER:  $PBS_SERVER"
echo "  PBS_ACCOUNT: $PBS_ACCOUNT"
echo "  PYTHONPATH:  $PYTHONPATH"
echo ""

# Launch the MCP server
python -m borealis_mcp.server
