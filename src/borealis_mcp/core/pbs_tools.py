"""Core PBS MCP tools for Borealis."""

import os
import traceback
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

from borealis_mcp.config.constants import ENV_PBS_ACCOUNT
from borealis_mcp.config.system import SystemConfig
from borealis_mcp.core.pbs_client import get_pbs_client, get_pbs_exception_class
from borealis_mcp.core.workspace import WorkspaceManager
from borealis_mcp.utils.errors import PBSOperationError, ValidationError
from borealis_mcp.utils.formatting import format_job_list, format_job_status
from borealis_mcp.utils.logging import get_logger
from borealis_mcp.utils.validation import (
    validate_account,
    validate_filesystems,
    validate_job_id,
    validate_node_count,
    validate_walltime,
)

logger = get_logger("pbs_tools")


def register_pbs_tools(
    mcp: FastMCP,
    system_config: SystemConfig,
    workspace_manager: Optional[WorkspaceManager] = None,
) -> None:
    """
    Register core PBS tools with the MCP server.

    Args:
        mcp: FastMCP server instance
        system_config: Current system configuration
        workspace_manager: Optional workspace manager for job workspaces
    """
    # Get default account from environment
    default_account = os.environ.get(ENV_PBS_ACCOUNT, "")
    PBSException = get_pbs_exception_class()

    @mcp.tool()
    def submit_pbs_job(
        script_path: Optional[str] = None,
        workspace_id: Optional[str] = None,
        queue: Optional[str] = None,
        job_name: Optional[str] = None,
        account: str = default_account,
        select_spec: Optional[str] = None,
        walltime: Optional[str] = None,
        filesystems: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Submit a PBS job from a script file.

        You can specify either script_path or workspace_id:
        - script_path: Direct path to the PBS submit script
        - workspace_id: ID of a workspace containing a submit script

        Args:
            script_path: Path to the PBS submit script
            workspace_id: Workspace ID (alternative to script_path)
            queue: Queue to submit to (default: system default queue)
            job_name: Name for the job
            account: PBS account/project name (defaults to PBS_ACCOUNT env var)
            select_spec: Node selection specification (e.g., "4" for 4 nodes)
            walltime: Wall time in HH:MM:SS format
            filesystems: Filesystem specification (e.g., "flare:home")

        Returns:
            Dictionary with job_id and submission status
        """
        # Resolve script_path from workspace_id if provided
        workspace_info = None
        if workspace_id and workspace_manager:
            workspace_info = workspace_manager.get_workspace(workspace_id)
            if not workspace_info:
                return {
                    "error": f"Workspace {workspace_id} not found",
                    "status": "failed",
                }
            if not workspace_info.script_path:
                return {
                    "error": f"Workspace {workspace_id} has no submit script",
                    "status": "failed",
                }
            script_path = workspace_info.script_path
            # Extract node count from workspace metadata if not explicitly provided
            if not select_spec and workspace_info.metadata:
                num_nodes = workspace_info.metadata.get("num_nodes")
                if num_nodes:
                    select_spec = str(num_nodes)
        elif not script_path:
            return {
                "error": "Either script_path or workspace_id must be provided",
                "status": "failed",
            }
        # Validate account
        try:
            account = validate_account(account)
        except ValidationError as e:
            return {"error": str(e), "status": "failed"}

        # Validate optional parameters
        if walltime:
            try:
                validate_walltime(walltime)
            except ValidationError as e:
                return {"error": str(e), "status": "failed"}

        if filesystems:
            try:
                validate_filesystems(filesystems)
            except ValidationError as e:
                return {"error": str(e), "status": "failed"}

        # Build attributes
        attrs: Dict[str, Any] = {"Account_Name": account}
        if job_name:
            attrs["Job_Name"] = job_name

        resource_list: Dict[str, str] = {}
        if select_spec:
            resource_list["select"] = select_spec
            resource_list["place"] = "scatter"  # Ensure nodes are on separate physical nodes
        if walltime:
            resource_list["walltime"] = walltime
        if filesystems:
            resource_list["filesystems"] = filesystems

        if resource_list:
            attrs["Resource_List"] = resource_list

        # Use default queue if not specified
        if not queue:
            default_queue = system_config.get_default_queue()
            queue = default_queue.name if default_queue else "workq"

        try:
            with get_pbs_client(system_config) as pbs:
                job_id = pbs.submit(script_path=script_path, queue=queue, attrs=attrs)
                logger.info(f"Submitted job {job_id} to queue {queue}")

                # Update workspace if used
                if workspace_info and workspace_manager:
                    workspace_manager.update_workspace(
                        workspace_info.workspace_id,
                        status="submitted",
                        job_id=job_id,
                    )

                result = {
                    "job_id": job_id,
                    "queue": queue,
                    "status": "submitted",
                    "system": system_config.display_name,
                }
                if workspace_info:
                    result["workspace_id"] = workspace_info.workspace_id
                    result["workspace_path"] = workspace_info.path
                return result
        except PBSException as e:
            logger.error(f"Job submission failed: {e}")
            return {"error": str(e), "status": "failed"}
        except RuntimeError as e:
            logger.error(f"Job submission failed: {e}")
            return {
                "error": str(e),
                "traceback": traceback.format_exc(),
                "status": "failed",
            }

    @mcp.tool()
    def get_job_status(job_id: str) -> Dict[str, Any]:
        """
        Get the status of a PBS job.

        Args:
            job_id: PBS job ID (e.g., "12345.aurora-pbs-01")

        Returns:
            Dictionary with job status information
        """
        try:
            validate_job_id(job_id)
        except ValidationError as e:
            return {"error": str(e)}

        try:
            with get_pbs_client(system_config) as pbs:
                jobs = pbs.stat_jobs(job_id=job_id)
                if not jobs:
                    return {"error": f"Job {job_id} not found"}
                return format_job_status(jobs[0])
        except PBSException as e:
            logger.error(f"Failed to get job status: {e}")
            return {"error": str(e)}
        except RuntimeError as e:
            logger.error(f"Failed to get job status: {e}")
            return {"error": str(e), "traceback": traceback.format_exc()}

    @mcp.tool()
    def list_jobs(
        state: Optional[str] = None, queue: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List PBS jobs, optionally filtered by state or queue.

        Args:
            state: Filter by job state (Q=queued, R=running, H=held)
            queue: Filter by queue name

        Returns:
            Dictionary with list of jobs and summary
        """
        try:
            with get_pbs_client(system_config) as pbs:
                if state:
                    jobs = pbs.select_jobs({"job_state": state})
                else:
                    jobs = pbs.stat_jobs()

                # Filter by queue if specified
                if queue:
                    jobs = [j for j in jobs if j.attrs.get("queue") == queue]

                formatted = format_job_list(jobs)
                summary = {}
                for job in jobs:
                    s = job.attrs.get("job_state", "unknown")
                    summary[s] = summary.get(s, 0) + 1

                return {
                    "jobs": formatted,
                    "total": len(jobs),
                    "summary": summary,
                    "system": system_config.display_name,
                }
        except PBSException as e:
            logger.error(f"Failed to list jobs: {e}")
            return {"error": str(e)}
        except RuntimeError as e:
            logger.error(f"Failed to list jobs: {e}")
            return {"error": str(e), "traceback": traceback.format_exc()}

    @mcp.tool()
    def delete_job(job_id: str, force: bool = False) -> Dict[str, Any]:
        """
        Delete a PBS job.

        Args:
            job_id: PBS job ID to delete
            force: Force deletion even if job is running

        Returns:
            Dictionary with deletion status
        """
        try:
            validate_job_id(job_id)
        except ValidationError as e:
            return {"error": str(e), "status": "failed"}

        try:
            with get_pbs_client(system_config) as pbs:
                pbs.delete_job(job_id, force=force)
                logger.info(f"Deleted job {job_id}")
                return {"job_id": job_id, "status": "deleted"}
        except PBSException as e:
            logger.error(f"Failed to delete job: {e}")
            return {"error": str(e), "status": "failed"}
        except RuntimeError as e:
            logger.error(f"Failed to delete job: {e}")
            return {"error": str(e), "traceback": traceback.format_exc(), "status": "failed"}

    @mcp.tool()
    def hold_job(job_id: str) -> Dict[str, Any]:
        """
        Hold a PBS job (prevent it from running).

        Args:
            job_id: PBS job ID to hold

        Returns:
            Dictionary with hold status
        """
        try:
            validate_job_id(job_id)
        except ValidationError as e:
            return {"error": str(e), "status": "failed"}

        try:
            with get_pbs_client(system_config) as pbs:
                pbs.hold_job(job_id)
                logger.info(f"Held job {job_id}")
                return {"job_id": job_id, "status": "held"}
        except PBSException as e:
            logger.error(f"Failed to hold job: {e}")
            return {"error": str(e), "status": "failed"}
        except RuntimeError as e:
            logger.error(f"Failed to hold job: {e}")
            return {"error": str(e), "traceback": traceback.format_exc(), "status": "failed"}

    @mcp.tool()
    def release_job(job_id: str) -> Dict[str, Any]:
        """
        Release a held PBS job.

        Args:
            job_id: PBS job ID to release

        Returns:
            Dictionary with release status
        """
        try:
            validate_job_id(job_id)
        except ValidationError as e:
            return {"error": str(e), "status": "failed"}

        try:
            with get_pbs_client(system_config) as pbs:
                pbs.release_job(job_id)
                logger.info(f"Released job {job_id}")
                return {"job_id": job_id, "status": "released"}
        except PBSException as e:
            logger.error(f"Failed to release job: {e}")
            return {"error": str(e), "status": "failed"}
        except RuntimeError as e:
            logger.error(f"Failed to release job: {e}")
            return {"error": str(e), "traceback": traceback.format_exc(), "status": "failed"}

    @mcp.tool()
    def get_queue_info(queue_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get information about PBS queues.

        Args:
            queue_name: Specific queue name (optional, returns all if not specified)

        Returns:
            Dictionary with queue information
        """
        try:
            with get_pbs_client(system_config) as pbs:
                queues = pbs.stat_queues(queue=queue_name)
                result = {}
                for q in queues:
                    result[q.name] = {
                        "enabled": q.attrs.get("enabled"),
                        "started": q.attrs.get("started"),
                        "total_jobs": q.attrs.get("total_jobs", "0"),
                        "max_walltime": q.attrs.get("resources_max.walltime"),
                        "max_nodes": q.attrs.get("resources_max.nodect"),
                    }
                return {"queues": result, "system": system_config.display_name}
        except PBSException as e:
            logger.error(f"Failed to get queue info: {e}")
            return {"error": str(e)}
        except RuntimeError as e:
            logger.error(f"Failed to get queue info: {e}")
            return {"error": str(e), "traceback": traceback.format_exc()}

    @mcp.tool()
    def get_system_info() -> Dict[str, Any]:
        """
        Get information about the current HPC system.

        Returns:
            Dictionary with system configuration details
        """
        default_queue = system_config.get_default_queue()
        return {
            "name": system_config.name,
            "display_name": system_config.display_name,
            "facility": system_config.facility,
            "pbs_server": system_config.pbs_server,
            "hardware": {
                "total_nodes": system_config.total_nodes,
                "cores_per_node": system_config.cores_per_node,
                "gpus_per_node": system_config.gpus_per_node,
                "gpu_type": system_config.gpu_type,
                "memory_per_node_gb": system_config.memory_per_node,
                "cpu_model": system_config.cpu_model,
                "interconnect": system_config.interconnect,
            },
            "queues": list(system_config.queues.keys()),
            "default_queue": default_queue.name if default_queue else None,
            "filesystems": system_config.filesystems,
            "default_filesystems": system_config.default_filesystems,
            "recommended_modules": system_config.recommended_modules,
        }
