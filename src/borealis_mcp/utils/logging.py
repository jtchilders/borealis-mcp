"""Logging configuration for Borealis MCP."""

import logging
import sys
from typing import Optional


def setup_logging(
    level: str = "INFO", format_string: Optional[str] = None
) -> logging.Logger:
    """
    Configure logging for Borealis MCP.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_string: Optional custom format string

    Returns:
        Configured logger instance
    """
    if format_string is None:
        format_string = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    # Create logger
    logger = logging.getLogger("borealis_mcp")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid duplicate handlers
    if not logger.handlers:
        # Create stderr handler (MCP uses stdout for protocol)
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.DEBUG)

        # Create formatter
        formatter = logging.Formatter(format_string, datefmt="%Y-%m-%d %H:%M:%S")
        handler.setFormatter(formatter)

        logger.addHandler(handler)

    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger instance.

    Args:
        name: Optional sub-logger name (e.g., "pbs_tools")

    Returns:
        Logger instance
    """
    if name:
        return logging.getLogger(f"borealis_mcp.{name}")
    return logging.getLogger("borealis_mcp")
