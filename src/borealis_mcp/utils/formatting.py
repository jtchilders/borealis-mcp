"""Output formatting utilities for Borealis MCP."""

from typing import Any, Dict, List, Protocol, runtime_checkable

from borealis_mcp.config.constants import JOB_STATES


@runtime_checkable
class JobInfoProtocol(Protocol):
    """Protocol for job info objects (works with both real and mock)."""

    name: str
    attrs: Dict[str, str]


@runtime_checkable
class QueueInfoProtocol(Protocol):
    """Protocol for queue info objects."""

    name: str
    attrs: Dict[str, str]


def format_job_status(job: JobInfoProtocol) -> Dict[str, Any]:
    """
    Format job status for MCP response.

    Args:
        job: JobInfo object (has .name and .attrs dict)

    Returns:
        Formatted dictionary with job information
    """
    attrs = job.attrs
    resource_list = {}
    resources_used = {}

    # Parse Resource_List entries (they come as separate keys like Resource_List.walltime)
    for key, value in attrs.items():
        if key.startswith("Resource_List."):
            resource_list[key.split(".", 1)[1]] = value
        elif key.startswith("resources_used."):
            resources_used[key.split(".", 1)[1]] = value

    # Get human-readable state
    state_code = attrs.get("job_state", "")
    state_desc = JOB_STATES.get(state_code, state_code)

    return {
        "job_id": job.name,
        "name": attrs.get("Job_Name"),
        "state": state_code,
        "state_description": state_desc,
        "queue": attrs.get("queue"),
        "account": attrs.get("Account_Name"),
        "owner": attrs.get("Job_Owner"),
        "walltime": {
            "requested": resource_list.get("walltime"),
            "used": resources_used.get("walltime"),
        },
        "nodes": {
            "requested": resource_list.get("select"),
            "assigned": attrs.get("exec_host"),
        },
        "created": attrs.get("ctime"),
        "started": attrs.get("stime"),
        "exit_status": attrs.get("Exit_status"),
    }


def format_queue_summary(queues: List[QueueInfoProtocol]) -> Dict[str, Any]:
    """
    Format queue summary for MCP response.

    Args:
        queues: List of QueueInfo objects

    Returns:
        Dictionary mapping queue names to their info
    """
    result = {}
    for queue in queues:
        attrs = queue.attrs
        result[queue.name] = {
            "enabled": attrs.get("enabled"),
            "started": attrs.get("started"),
            "total_jobs": int(attrs.get("total_jobs", 0)),
            "state_count": attrs.get("state_count", ""),
            "max_walltime": attrs.get("resources_max.walltime"),
            "max_nodes": attrs.get("resources_max.nodect"),
        }
    return result


def format_job_list(jobs: List[JobInfoProtocol]) -> List[Dict[str, Any]]:
    """
    Format a list of jobs for MCP response.

    Args:
        jobs: List of JobInfo objects

    Returns:
        List of formatted job dictionaries
    """
    return [format_job_status(job) for job in jobs]


def format_job_summary(jobs: List[JobInfoProtocol]) -> Dict[str, int]:
    """
    Get job count summary by state.

    Args:
        jobs: List of JobInfo objects

    Returns:
        Dictionary mapping state codes to counts
    """
    summary: Dict[str, int] = {}
    for job in jobs:
        state = job.attrs.get("job_state", "unknown")
        summary[state] = summary.get(state, 0) + 1
    return summary
