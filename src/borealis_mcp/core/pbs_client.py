"""PBS client wrapper for Borealis MCP.

This module provides a unified interface to PBS, automatically selecting
between the real pbs_api client and a mock client for local development.
"""

import os
from contextlib import contextmanager
from typing import Any, Iterator, Optional, Type, Union

from borealis_mcp.config.constants import ENV_BOREALIS_MOCK_PBS
from borealis_mcp.config.system import SystemConfig
from borealis_mcp.core.mock_pbs_client import (
    MockPBSClient,
    MockPBSException,
    is_mock_mode,
)
from borealis_mcp.utils.errors import PBSConnectionError
from borealis_mcp.utils.logging import get_logger

logger = get_logger("pbs_client")

# Type aliases for the client types
PBSClientType = Union[MockPBSClient, Any]  # Any is for real PBSClient
PBSExceptionType = Union[Type[MockPBSException], Any]


def _get_pbs_client_class() -> tuple:
    """
    Get the appropriate PBS client class based on environment.

    Returns:
        Tuple of (PBSClient class, PBSException class)

    Raises:
        RuntimeError: If pbs_api is not available and mock mode is not enabled
    """
    if is_mock_mode():
        logger.debug("Using mock PBS client")
        return MockPBSClient, MockPBSException

    try:
        from pbs_api import PBSClient, PBSException

        logger.debug("Using real PBS client")
        return PBSClient, PBSException
    except ImportError as e:
        raise RuntimeError(
            "pbs_api module not available. Either:\n"
            "  1. Run on an HPC login node with pbs_ifl available, or\n"
            f"  2. Set {ENV_BOREALIS_MOCK_PBS}=1 for local development\n"
            f"Original error: {e}"
        ) from e


# Get the client classes at module load time
try:
    PBSClient, PBSException = _get_pbs_client_class()
except RuntimeError:
    # If we can't load, set to None and let it fail at runtime
    PBSClient = None  # type: ignore
    PBSException = MockPBSException


@contextmanager
def get_pbs_client(
    system_config: SystemConfig, server: Optional[str] = None
) -> Iterator[PBSClientType]:
    """
    Context manager for PBS client connections.

    Args:
        system_config: System configuration object
        server: PBS server hostname (defaults to system config)

    Yields:
        Connected PBS client

    Raises:
        PBSConnectionError: If connection fails
        RuntimeError: If PBS client is not available
    """
    if PBSClient is None:
        raise RuntimeError(
            "PBS client not available. Either run on an HPC login node or "
            f"set {ENV_BOREALIS_MOCK_PBS}=1 for local development."
        )

    server = server or system_config.pbs_server

    try:
        with PBSClient(server=server) as client:
            yield client
    except PBSException as e:
        raise PBSConnectionError(
            server=server,
            system_name=system_config.display_name,
            original_error=str(e),
        ) from e


def validate_pbs_connection(system_config: SystemConfig) -> bool:
    """
    Validate PBS connection is available.

    Args:
        system_config: System configuration object

    Returns:
        True if connection successful, False otherwise
    """
    try:
        with get_pbs_client(system_config) as pbs:
            pbs.stat_server()
        return True
    except (PBSConnectionError, RuntimeError):
        return False


def get_pbs_exception_class() -> PBSExceptionType:
    """Get the appropriate PBS exception class.

    Returns:
        PBSException class (real or mock)
    """
    return PBSException
