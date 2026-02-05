"""Hello World MCP application."""

import os
from typing import Any, Dict, Optional

from fastmcp import FastMCP

from borealis_mcp.applications.base import ApplicationBase
from borealis_mcp.applications.hello_world.templates import HelloWorldTemplates
from borealis_mcp.config.constants import ENV_PBS_ACCOUNT
from borealis_mcp.config.system import SystemConfig
from borealis_mcp.utils.logging import get_logger
from borealis_mcp.utils.validation import validate_account

logger = get_logger("hello_world")


class Application(ApplicationBase):
    """Simple MPI hello world application for testing and demonstration."""

    @property
    def name(self) -> str:
        return "hello_world"

    @property
    def description(self) -> str:
        return "MPI Hello World - prints rank and hostname from each MPI process"

    def supports_system(self, system_config: SystemConfig) -> bool:
        """Hello world works on any system."""
        return True

    def register_tools(
        self,
        mcp: FastMCP,
        system_config: SystemConfig,
        app_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register hello_world-specific tools."""

        # Get settings from app config or use defaults
        if app_config:
            modules = app_config.get("modules", system_config.recommended_modules)
            mpi_command = app_config.get("mpi", {}).get("command", "mpiexec")
            mpi_flags = app_config.get("mpi", {}).get("flags", [])
            env_vars = app_config.get("environment", {})
            default_walltime = app_config.get("defaults", {}).get(
                "walltime", "00:30:00"
            )
            default_queue = app_config.get("defaults", {}).get("queue", "debug")
        else:
            # Use system defaults
            modules = system_config.recommended_modules
            mpi_command = "mpiexec"
            mpi_flags = []
            env_vars = {}
            default_walltime = "00:30:00"
            default_queue = "debug"

        # Get default account from environment
        default_account = os.environ.get(ENV_PBS_ACCOUNT, "")

        @mcp.tool()
        def build_hello_world_submit_script(
            script_path: str,
            num_nodes: int,
            ranks_per_node: int,
            account: str = default_account,
            walltime: str = default_walltime,
            queue: str = default_queue,
            job_name: str = "hello_world",
        ) -> Dict[str, Any]:
            """
            Generate PBS submit script for MPI Hello World.

            Prints rank number and hostname from each MPI process.
            Automatically adapts to the current system configuration.

            Args:
                script_path: Where to save the submit script
                num_nodes: Number of nodes to use
                ranks_per_node: MPI ranks per node
                account: PBS account/project name (defaults to PBS_ACCOUNT env var)
                walltime: Wall time in HH:MM:SS format
                queue: Queue name
                job_name: Name for the PBS job

            Returns:
                Dictionary with script path and configuration details
            """
            try:
                account = validate_account(account)
            except Exception as e:
                return {"error": str(e), "status": "failed"}

            template = HelloWorldTemplates.generate_submit_script(
                system_config=system_config,
                num_nodes=num_nodes,
                ranks_per_node=ranks_per_node,
                walltime=walltime,
                queue=queue,
                job_name=job_name,
                account=account,
                modules=modules,
                mpi_command=mpi_command,
                mpi_flags=mpi_flags,
                env_vars=env_vars,
            )

            with open(script_path, "w") as f:
                f.write(template)

            logger.info(f"Generated hello_world script: {script_path}")

            return {
                "script_path": script_path,
                "status": "created",
                "system": system_config.display_name,
                "configuration": {
                    "nodes": num_nodes,
                    "ranks_per_node": ranks_per_node,
                    "total_ranks": num_nodes * ranks_per_node,
                    "queue": queue,
                    "walltime": walltime,
                    "account": account,
                },
            }

        @mcp.tool()
        def get_hello_world_info() -> Dict[str, Any]:
            """
            Get information about hello_world configuration for current system.

            Returns:
                Dictionary with system-specific settings and recommendations
            """
            default_queue_config = system_config.get_queue(default_queue)
            max_nodes = (
                default_queue_config.max_nodes if default_queue_config else "unknown"
            )

            return {
                "application": "hello_world",
                "description": self.description,
                "system": system_config.display_name,
                "modules": modules,
                "mpi_command": mpi_command,
                "mpi_flags": mpi_flags,
                "environment": env_vars,
                "defaults": {
                    "walltime": default_walltime,
                    "queue": default_queue,
                    "account": default_account or "(set PBS_ACCOUNT env var)",
                },
                "recommended_usage": {
                    "min_nodes": 1,
                    "max_nodes": max_nodes,
                    "typical_ranks_per_node": system_config.cores_per_node,
                },
                "example": (
                    f"build_hello_world_submit_script("
                    f"script_path='submit.sh', num_nodes=2, ranks_per_node=4, "
                    f"account='myproject')"
                ),
            }
