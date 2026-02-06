"""Workspace MCP tools for Borealis."""

from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

from borealis_mcp.config.system import SystemConfig, SystemConfigLoader
from borealis_mcp.core.workspace import WorkspaceManager
from borealis_mcp.utils.logging import get_logger

logger = get_logger("workspace_tools")


def register_workspace_tools(
    mcp: FastMCP,
    system_config: SystemConfig,
    config_loader: SystemConfigLoader,
) -> WorkspaceManager:
    """
    Register workspace management tools with the MCP server.

    Args:
        mcp: FastMCP server instance
        system_config: Current system configuration
        config_loader: Configuration loader for server settings

    Returns:
        WorkspaceManager instance for use by other tools
    """
    # Get workspace base path from config
    server_config = config_loader.load_server_config()
    workspace_config = server_config.get("workspace", {})
    base_path = workspace_config.get("base_path")

    # Create workspace manager
    workspace_manager = WorkspaceManager(
        base_path=base_path,
        system_name=system_config.name,
    )

    logger.info(f"Workspace base path: {workspace_manager.base_path}")

    @mcp.tool()
    def create_job_workspace(
        job_name: str,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new job workspace directory.

        Creates a directory on the HPC filesystem where job scripts,
        inputs, and outputs will be stored. This should be called
        before building submit scripts.

        Args:
            job_name: Name for the job (used in directory name)
            description: Optional description of the job

        Returns:
            Dictionary with workspace_id, path, and status
        """
        try:
            metadata = {}
            if description:
                metadata["description"] = description

            info = workspace_manager.create_workspace(
                job_name=job_name,
                metadata=metadata,
            )

            logger.info(f"Created workspace {info.workspace_id} at {info.path}")

            return {
                "workspace_id": info.workspace_id,
                "path": info.path,
                "job_name": info.job_name,
                "created_at": info.created_at,
                "system": info.system,
                "status": "created",
            }
        except OSError as e:
            logger.error(f"Failed to create workspace: {e}")
            return {"error": str(e), "status": "failed"}

    @mcp.tool()
    def get_workspace_info(workspace_id: str) -> Dict[str, Any]:
        """
        Get information about a job workspace.

        Args:
            workspace_id: Workspace identifier returned by create_job_workspace

        Returns:
            Dictionary with workspace details including path, status, and job_id
        """
        info = workspace_manager.get_workspace(workspace_id)
        if not info:
            return {"error": f"Workspace {workspace_id} not found", "status": "not_found"}

        return {
            "workspace_id": info.workspace_id,
            "path": info.path,
            "job_name": info.job_name,
            "created_at": info.created_at,
            "system": info.system,
            "status": info.status,
            "job_id": info.job_id,
            "script_path": info.script_path,
            "metadata": info.metadata,
        }

    @mcp.tool()
    def list_workspaces(
        status: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """
        List existing job workspaces.

        Args:
            status: Filter by status (active, submitted, completed, failed)
            limit: Maximum number of workspaces to return (default: 20)

        Returns:
            Dictionary with list of workspaces and count
        """
        workspaces = workspace_manager.list_workspaces(status=status, limit=limit)

        return {
            "workspaces": [
                {
                    "workspace_id": w.workspace_id,
                    "path": w.path,
                    "job_name": w.job_name,
                    "created_at": w.created_at,
                    "status": w.status,
                    "job_id": w.job_id,
                }
                for w in workspaces
            ],
            "count": len(workspaces),
            "base_path": str(workspace_manager.base_path),
        }

    @mcp.tool()
    def cleanup_workspace(
        workspace_id: str,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Remove a job workspace directory.

        Args:
            workspace_id: Workspace identifier
            force: If True, remove even if job is still active/submitted

        Returns:
            Dictionary with cleanup status
        """
        info = workspace_manager.get_workspace(workspace_id)
        if not info:
            return {"error": f"Workspace {workspace_id} not found", "status": "not_found"}

        if workspace_manager.cleanup_workspace(workspace_id, force=force):
            return {
                "workspace_id": workspace_id,
                "path": info.path,
                "status": "removed",
            }
        else:
            return {
                "workspace_id": workspace_id,
                "path": info.path,
                "current_status": info.status,
                "status": "not_removed",
                "message": "Workspace has active/submitted job. Use force=True to remove anyway.",
            }

    @mcp.tool()
    def get_workspace_base_path() -> Dict[str, Any]:
        """
        Get the base path where job workspaces are created.

        Returns:
            Dictionary with base_path and configuration info
        """
        return {
            "base_path": str(workspace_manager.base_path),
            "system": system_config.name,
            "exists": workspace_manager.base_path.exists(),
        }

    return workspace_manager
