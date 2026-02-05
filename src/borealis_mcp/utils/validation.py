"""Input validation utilities for Borealis MCP."""

import re
from typing import Optional

from borealis_mcp.config.constants import (
    FILESYSTEMS_REGEX,
    JOB_ID_REGEX,
    WALLTIME_REGEX,
)
from borealis_mcp.utils.errors import ValidationError


def validate_job_id(job_id: str) -> None:
    """
    Validate PBS job ID format.

    Args:
        job_id: Job ID to validate (e.g., "12345.aurora-pbs-01")

    Raises:
        ValidationError: If job ID format is invalid
    """
    if not JOB_ID_REGEX.match(job_id):
        raise ValidationError(
            f"Invalid job ID format: '{job_id}'. "
            f"Expected format: <number>.<server> (e.g., 12345.aurora-pbs-01)"
        )


def validate_walltime(walltime: str) -> None:
    """
    Validate walltime format (HH:MM:SS).

    Args:
        walltime: Walltime string to validate

    Raises:
        ValidationError: If walltime format is invalid
    """
    if not WALLTIME_REGEX.match(walltime):
        raise ValidationError(
            f"Invalid walltime format: '{walltime}'. Expected HH:MM:SS (e.g., 01:30:00)"
        )


def validate_filesystems(filesystems: str) -> None:
    """
    Validate filesystem specification format.

    Args:
        filesystems: Filesystem spec to validate (e.g., "flare:home")

    Raises:
        ValidationError: If filesystem format is invalid
    """
    if not FILESYSTEMS_REGEX.match(filesystems):
        raise ValidationError(
            f"Invalid filesystems format: '{filesystems}'. "
            f"Expected format like 'flare:home' (colon-separated names)"
        )


def validate_node_count(nodes: int, max_nodes: Optional[int] = None) -> None:
    """
    Validate node count.

    Args:
        nodes: Number of nodes requested
        max_nodes: Maximum allowed nodes (optional)

    Raises:
        ValidationError: If node count is invalid
    """
    if nodes < 1:
        raise ValidationError("Node count must be at least 1")
    if max_nodes is not None and nodes > max_nodes:
        raise ValidationError(
            f"Requested {nodes} nodes exceeds queue limit of {max_nodes}"
        )


def validate_queue_name(queue: str, available_queues: Optional[list] = None) -> None:
    """
    Validate queue name.

    Args:
        queue: Queue name to validate
        available_queues: List of valid queue names (optional)

    Raises:
        ValidationError: If queue name is invalid
    """
    if not queue or not queue.strip():
        raise ValidationError("Queue name cannot be empty")

    if available_queues and queue not in available_queues:
        raise ValidationError(
            f"Unknown queue: '{queue}'. Available queues: {available_queues}"
        )


def validate_account(account: Optional[str]) -> str:
    """
    Validate PBS account is provided.

    Args:
        account: Account/project name

    Returns:
        The validated account string

    Raises:
        ValidationError: If account is not provided
    """
    if not account or not account.strip():
        raise ValidationError(
            "PBS account is required. Set PBS_ACCOUNT environment variable "
            "or pass account parameter explicitly."
        )
    return account.strip()
