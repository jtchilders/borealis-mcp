"""Borealis MCP Server - AI agent interface for ALCF supercomputers."""

import argparse
import os
import socket
import sys
from typing import Optional

from fastmcp import FastMCP

from borealis_mcp.applications.registry import ApplicationRegistry
from borealis_mcp.config.constants import ENV_BOREALIS_SYSTEM
from borealis_mcp.config.system import SystemConfigLoader
from borealis_mcp.core.mock_pbs_client import is_mock_mode
from borealis_mcp.core.pbs_prompts import register_pbs_prompts
from borealis_mcp.core.pbs_resources import register_pbs_resources
from borealis_mcp.core.pbs_tools import register_pbs_tools
from borealis_mcp.utils.logging import get_logger, setup_logging


def create_server(
    system_name: Optional[str] = None, config_dir: Optional[str] = None
) -> FastMCP:
    """
    Create and configure the Borealis MCP server.

    Args:
        system_name: Override system name (defaults to auto-detection)
        config_dir: Override config directory path

    Returns:
        Configured FastMCP server instance
    """
    # Setup logging
    logger = setup_logging()

    # Initialize MCP server
    mcp = FastMCP("Borealis MCP", version="0.1.0")

    # Load system configurations
    config_loader = SystemConfigLoader(
        config_dir=config_dir if config_dir else None
    )

    # Load server config (for default_system, logging settings, etc.)
    server_config = config_loader.load_server_config()

    # Apply logging level from config
    log_level = server_config.get("logging", {}).get("level", "INFO")
    import logging
    logging.getLogger("borealis_mcp").setLevel(
        getattr(logging, log_level.upper(), logging.INFO)
    )

    # Determine current system
    # Priority: 1) argument, 2) env var, 3) config default, 4) auto-detect, 5) first available
    current_system_name = system_name

    if not current_system_name:
        current_system_name = os.environ.get(ENV_BOREALIS_SYSTEM)

    if not current_system_name:
        current_system_name = server_config.get("default_system")

    if not current_system_name:
        # Try to auto-detect based on hostname
        current_system_name = SystemConfigLoader.detect_system_from_hostname()

    if not current_system_name:
        # Default to first available system
        available = config_loader.list_available_systems()
        if available:
            current_system_name = available[0]
        else:
            logger.error("No system configurations found in config/systems/")
            raise RuntimeError(
                "No system configurations found. Create YAML files in config/systems/ "
                "or set BOREALIS_SYSTEM environment variable."
            )

    # Load and set current system
    try:
        config_loader.set_current_system(current_system_name)
        current_system = config_loader.get_current_system()
    except FileNotFoundError as e:
        logger.error(f"Failed to load system configuration: {e}")
        raise

    logger.info(f"Borealis MCP initialized for {current_system.display_name}")
    logger.info(f"Available systems: {', '.join(config_loader.list_available_systems())}")

    # Check for mock mode
    if is_mock_mode():
        logger.warning(
            "Running in MOCK PBS mode - no real PBS operations will be performed"
        )

    # Register core PBS capabilities
    register_pbs_tools(mcp, current_system)
    register_pbs_resources(mcp, current_system, config_loader)
    register_pbs_prompts(mcp, current_system)

    # Auto-discover and register applications
    registry = ApplicationRegistry()
    registry.discover_applications()
    registry.register_all(mcp, current_system, config_loader)

    return mcp


def main() -> None:
    """Entry point for the Borealis MCP server."""
    parser = argparse.ArgumentParser(
        description="Borealis MCP Server - AI agent interface for ALCF supercomputers"
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport protocol (stdio for local, http for remote)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (only for HTTP transport)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9000,
        help="Port to bind to (only for HTTP transport)",
    )
    parser.add_argument(
        "--path",
        default="/mcp",
        help="URL path for MCP endpoint (only for HTTP transport)",
    )
    parser.add_argument(
        "--system",
        default=None,
        help="Override system name (e.g., aurora, polaris)",
    )
    parser.add_argument(
        "--config-dir",
        default=None,
        help="Override config directory path",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Enable mock PBS mode for local development",
    )

    args = parser.parse_args()

    # Enable mock mode if requested
    if args.mock:
        os.environ["BOREALIS_MOCK_PBS"] = "1"

    # Create the server
    try:
        mcp = create_server(
            system_name=args.system,
            config_dir=args.config_dir,
        )
    except Exception as e:
        print(f"Error: Failed to initialize server: {e}", file=sys.stderr)
        sys.exit(1)

    logger = get_logger()

    # Run the server
    if args.transport == "http":
        logger.info(
            f"Starting Borealis MCP in HTTP mode on {args.host}:{args.port}{args.path}"
        )
        logger.info("Make sure your SSH tunnel is configured to forward this port")
        mcp.run(transport="http", host=args.host, port=args.port, path=args.path)
    else:
        logger.info("Starting Borealis MCP in STDIO mode")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
