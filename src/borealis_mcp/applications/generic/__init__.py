"""Generic MCP application for arbitrary executables."""

import os
from typing import TYPE_CHECKING, Any, Dict, Optional

from fastmcp import FastMCP

from borealis_mcp.applications.base import ApplicationBase
from borealis_mcp.applications.generic.templates import GenericTemplates
from borealis_mcp.config.constants import ENV_PBS_ACCOUNT
from borealis_mcp.config.system import SystemConfig
from borealis_mcp.utils.logging import get_logger
from borealis_mcp.utils.validation import validate_account

if TYPE_CHECKING:
    from borealis_mcp.core.workspace import WorkspaceManager

logger = get_logger("generic")


class Application(ApplicationBase):
    """Generic job support for arbitrary executables."""

    @property
    def name(self) -> str:
        return "generic"

    @property
    def description(self) -> str:
        return "Generic PBS job submission for any executable"

    def register_tools(
        self,
        mcp: FastMCP,
        system_config: SystemConfig,
        app_config: Optional[Dict[str, Any]] = None,
        workspace_manager: Optional["WorkspaceManager"] = None,
    ) -> None:
        """Register generic tools."""

        # Get default account from environment
        default_account = os.environ.get(ENV_PBS_ACCOUNT, "")

        # Get defaults from app config or system config
        if app_config:
            default_modules = app_config.get(
                "modules", system_config.recommended_modules
            )
            default_walltime = app_config.get("defaults", {}).get(
                "walltime", "01:00:00"
            )
            default_queue = app_config.get("defaults", {}).get("queue", "debug")
        else:
            default_modules = system_config.recommended_modules
            default_walltime = "01:00:00"
            default_queue = "debug"

        @mcp.tool()
        def build_generic_submit_script(
            executable: str,
            workspace_id: Optional[str] = None,
            account: str = default_account,
            arguments: str = "",
            num_nodes: int = 1,
            mpi_ranks_per_node: int = 1,
            walltime: str = default_walltime,
            queue: str = default_queue,
            job_name: str = "generic_job",
            environment_setup: str = "",
        ) -> Dict[str, Any]:
            """
            Generate basic PBS submit script for any executable.

            IMPORTANT: Do NOT use this for applications that have specialized tools.
            Use the application-specific tool instead (e.g., build_pepper_submit_script
            for Pepper jobs). Those tools know the correct command-line arguments and
            handle GPU affinity automatically.

            The script is created in a job workspace. If no workspace_id is
            provided, a new workspace will be created automatically.

            Args:
                executable: Path to executable or command
                workspace_id: Optional workspace ID (creates new workspace if not provided)
                account: PBS account/project name (defaults to PBS_ACCOUNT env var)
                arguments: Command-line arguments
                num_nodes: Number of nodes
                mpi_ranks_per_node: MPI ranks per node
                walltime: Wall time in HH:MM:SS format
                queue: Queue name
                job_name: Name for the PBS job
                environment_setup: Custom environment commands (bash script fragment)

            Returns:
                Dictionary with workspace_id, script_path, and configuration details
            """
            if workspace_manager is None:
                return {
                    "error": "Workspace manager not available",
                    "status": "failed",
                }

            try:
                account = validate_account(account)
            except Exception as e:
                return {"error": str(e), "status": "failed"}

            # Get or create workspace
            if workspace_id:
                workspace_info = workspace_manager.get_workspace(workspace_id)
                if not workspace_info:
                    return {
                        "error": f"Workspace {workspace_id} not found",
                        "status": "failed",
                    }
            else:
                # Create a new workspace
                try:
                    workspace_info = workspace_manager.create_workspace(
                        job_name=job_name,
                        metadata={
                            "application": "generic",
                            "executable": executable,
                            "num_nodes": num_nodes,
                            "mpi_ranks_per_node": mpi_ranks_per_node,
                        },
                    )
                except OSError as e:
                    return {"error": f"Failed to create workspace: {e}", "status": "failed"}

            # Generate script path in workspace
            script_path = workspace_manager.get_script_path(
                workspace_info.workspace_id, "submit.sh"
            )

            template = GenericTemplates.generate_submit_script(
                system_config=system_config,
                executable=executable,
                arguments=arguments,
                account=account,
                num_nodes=num_nodes,
                mpi_ranks_per_node=mpi_ranks_per_node,
                walltime=walltime,
                queue=queue,
                job_name=job_name,
                environment_setup=environment_setup,
                modules=default_modules,
            )

            with open(script_path, "w") as f:
                f.write(template)

            # Update workspace with script path
            workspace_manager.update_workspace(
                workspace_info.workspace_id,
                script_path=script_path,
            )

            logger.info(f"Generated generic script: {script_path}")

            return {
                "workspace_id": workspace_info.workspace_id,
                "workspace_path": workspace_info.path,
                "script_path": script_path,
                "status": "created",
                "system": system_config.display_name,
                "configuration": {
                    "executable": executable,
                    "arguments": arguments,
                    "nodes": num_nodes,
                    "mpi_ranks_per_node": mpi_ranks_per_node,
                    "total_ranks": num_nodes * mpi_ranks_per_node,
                    "queue": queue,
                    "walltime": walltime,
                    "account": account,
                },
            }

        @mcp.tool()
        def get_generic_info() -> Dict[str, Any]:
            """
            Get information about generic job configuration for current system.

            Returns:
                Dictionary with system-specific settings and usage info
            """
            default_queue_config = system_config.get_queue(default_queue)
            max_nodes = (
                default_queue_config.max_nodes if default_queue_config else "unknown"
            )

            workspace_base = None
            if workspace_manager:
                workspace_base = str(workspace_manager.base_path)

            return {
                "application": "generic",
                "description": self.description,
                "system": system_config.display_name,
                "modules": default_modules,
                "defaults": {
                    "walltime": default_walltime,
                    "queue": default_queue,
                    "account": default_account or "(set PBS_ACCOUNT env var)",
                    "num_nodes": 1,
                    "mpi_ranks_per_node": 1,
                },
                "workspace_base_path": workspace_base,
                "system_info": {
                    "cores_per_node": system_config.cores_per_node,
                    "gpus_per_node": system_config.gpus_per_node,
                    "max_nodes_debug": max_nodes,
                },
                "example": (
                    "build_generic_submit_script("
                    "executable='./my_program', "
                    "arguments='--input data.txt', "
                    "num_nodes=2, "
                    "account='myproject')"
                ),
            }
