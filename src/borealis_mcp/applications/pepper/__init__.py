"""Pepper MCP application for Borealis.

Pepper (Portable Engine for the Production of Parton-level Event Records)
is an efficient parton-level event generator for high-energy physics
simulations. This application provides tools for launching Pepper jobs
on Aurora with GPU and MPI support.
"""

import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from fastmcp import FastMCP

from borealis_mcp.applications.base import ApplicationBase
from borealis_mcp.applications.pepper.templates import PepperTemplates
from borealis_mcp.config.constants import ENV_PBS_ACCOUNT
from borealis_mcp.config.system import SystemConfig
from borealis_mcp.utils.logging import get_logger
from borealis_mcp.utils.validation import validate_account

if TYPE_CHECKING:
    from borealis_mcp.core.workspace import WorkspaceManager

logger = get_logger("pepper")


class Application(ApplicationBase):
    """Pepper parton-level event generator for HPC systems.

    Pepper is optimized for GPU acceleration using Kokkos and supports
    MPI for distributed computing. On Aurora, it runs on Intel Data Center
    GPUs with proper tile-based affinity binding.
    """

    @property
    def name(self) -> str:
        return "pepper"

    @property
    def description(self) -> str:
        return (
            "Pepper - Portable parton-level event generator for high-energy physics. "
            "Supports GPU acceleration and MPI parallelization."
        )

    def supports_system(self, system_config: SystemConfig) -> bool:
        """Pepper is optimized for Aurora but can run on other systems."""
        # Currently optimized for Aurora, but could support other GPU systems
        return system_config.name in ["aurora", "polaris", "sunspot"]

    def register_tools(
        self,
        mcp: FastMCP,
        system_config: SystemConfig,
        app_config: Optional[Dict[str, Any]] = None,
        workspace_manager: Optional["WorkspaceManager"] = None,
    ) -> None:
        """Register Pepper-specific tools."""

        # Get settings from app config or system defaults
        if app_config:
            modules = app_config.get("modules", system_config.recommended_modules)
            mpi_command = app_config.get("mpi", {}).get("command", "mpiexec")
            mpi_flags = app_config.get("mpi", {}).get("flags", [])
            env_vars = app_config.get("environment") or {}
            default_walltime = app_config.get("defaults", {}).get(
                "walltime", "01:00:00"
            )
            default_queue = app_config.get("defaults", {}).get("queue", "debug")
            default_pepper_path = app_config.get("defaults", {}).get(
                "pepper_executable", ""
            )
            # Fullstack setup paths (preferred over direct executable)
            fullstack_setup = app_config.get("fullstack_setup")
            pepper_setup = app_config.get("pepper_setup")
        else:
            # Use system defaults
            modules = system_config.recommended_modules
            custom_settings = getattr(system_config, "custom_settings", {}) or {}
            mpi_settings = custom_settings.get("mpi", {})
            mpi_command = mpi_settings.get("command", "mpiexec")
            mpi_flags = mpi_settings.get("flags", [])
            env_vars = custom_settings.get("environment", {})
            default_walltime = "01:00:00"
            default_queue = "debug"
            default_pepper_path = ""
            fullstack_setup = None
            pepper_setup = None

        # Get default account from environment
        default_account = os.environ.get(ENV_PBS_ACCOUNT, "")

        # Get GPU configuration from system
        gpus_per_node = getattr(system_config, "gpus_per_node", 6)
        tiles_per_gpu = getattr(system_config, "tiles_per_gpu", 2)
        custom_settings = getattr(system_config, "custom_settings", {}) or {}
        # Use 1 rank per GPU (not per tile) for pepper - simpler and works well
        default_ranks_per_node = gpus_per_node  # 6 ranks per node on Aurora

        @mcp.tool()
        def build_pepper_submit_script(
            process: str,
            collision_energy: float,
            n_events: int,
            num_nodes: int = 1,
            ranks_per_node: int = default_ranks_per_node,
            workspace_id: Optional[str] = None,
            account: str = default_account,
            walltime: str = default_walltime,
            queue: str = default_queue,
            job_name: str = "pepper",
            pepper_executable: Optional[str] = None,
            output_format: str = "hdf5",
            output_file: Optional[str] = None,
            batch_size: int = 1024,
            use_gpu: bool = True,
            extra_args: str = "",
        ) -> Dict[str, Any]:
            """
            Generate PBS submit script for Pepper event generator.

            ALWAYS use this tool for Pepper jobs - it handles the correct command-line
            arguments and GPU affinity automatically. Do NOT use build_generic_submit_script
            for Pepper.

            Creates a PBS script optimized for running Pepper on Aurora with
            Intel GPUs. Automatically configures MPI ranks and GPU affinity
            for optimal performance.

            Args:
                process: Physics process to simulate (e.g., "d db -> e+ e-", "g g -> t tb")
                collision_energy: Center-of-mass energy in GeV
                n_events: Number of events to generate
                num_nodes: Number of compute nodes (default: 1)
                ranks_per_node: MPI ranks per node (default: 12 for Aurora, 1 per GPU tile)
                workspace_id: Optional workspace ID (creates new if not provided)
                account: PBS account/project name (defaults to PBS_ACCOUNT env var)
                walltime: Wall time in HH:MM:SS format (default: 01:00:00)
                queue: Queue name (default: debug)
                job_name: Name for the PBS job (default: pepper)
                pepper_executable: Full path to pepper executable (uses config default if set)
                output_format: Output format - "hdf5", "hepmc3", or "disabled" (default: hdf5)
                output_file: Output filename (default: auto-generated based on process)
                batch_size: Batch size for GPU processing (default: 1024)
                use_gpu: Enable GPU acceleration (default: True)
                extra_args: Additional command-line arguments for pepper

            Returns:
                Dictionary with workspace_id, script_path, and configuration details

            Example:
                build_pepper_submit_script(
                    process="d db -> e+ e-",
                    collision_energy=91.2,
                    n_events=10000,
                    num_nodes=2,
                    account="myproject",
                    pepper_executable="/path/to/pepper/bin/pepper"
                )
            """
            if workspace_manager is None:
                return {
                    "error": "Workspace manager not available",
                    "status": "failed",
                }

            # Resolve pepper executable: use provided value, fall back to config default
            resolved_pepper_executable = pepper_executable or default_pepper_path

            # Validate: either fullstack setup or pepper_executable must be provided
            use_fullstack = fullstack_setup is not None and pepper_setup is not None
            if not use_fullstack and not resolved_pepper_executable:
                return {
                    "error": "Either fullstack setup paths or pepper_executable is required.",
                    "status": "failed",
                }

            try:
                account = validate_account(account)
            except Exception as e:
                return {"error": str(e), "status": "failed"}

            # Build pepper command-line arguments
            pepper_args_parts: List[str] = [
                f'--process "{process}"',
                f"--collision-energy {collision_energy}",
                f"--n-events {n_events}",
                f"--batch-size {batch_size}",
            ]

            # Handle output format - always produce output in workspace directory
            if output_format == "disabled":
                pepper_args_parts.append("--output-disabled")
                resolved_output_file = None
            else:
                # Determine output filename - use provided or generate default
                if output_file:
                    resolved_output_file = output_file
                else:
                    # Auto-generate filename based on process
                    safe_process = process.replace(" ", "_").replace(">", "to").replace("-", "")
                    if output_format == "hepmc3":
                        resolved_output_file = f"{safe_process}_events.lhe"
                    else:
                        resolved_output_file = f"{safe_process}_events.hdf5"

                # Output path will be set in template using workspace_path
                # Just pass the filename here
                pepper_args_parts.append(f'--output "{resolved_output_file}"')

                if output_format == "hepmc3":
                    pepper_args_parts.append("--hepmc3-output")
                # hdf5 is the default, no flag needed

            # Add any extra arguments
            if extra_args:
                pepper_args_parts.append(extra_args)

            pepper_args = " ".join(pepper_args_parts)

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
                            "application": "pepper",
                            "num_nodes": num_nodes,
                            "ranks_per_node": ranks_per_node,
                            "process": process,
                            "collision_energy": collision_energy,
                            "n_events": n_events,
                            "use_gpu": use_gpu,
                        },
                    )
                except OSError as e:
                    return {
                        "error": f"Failed to create workspace: {e}",
                        "status": "failed",
                    }

            # Generate script path in workspace
            script_path = workspace_manager.get_script_path(
                workspace_info.workspace_id, "submit.sh"
            )

            # Generate the submit script
            template = PepperTemplates.generate_submit_script(
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
                pepper_executable=resolved_pepper_executable,
                pepper_args=pepper_args,
                use_gpu=use_gpu,
                fullstack_setup=fullstack_setup,
                pepper_setup=pepper_setup,
                workspace_path=workspace_info.path,
            )

            with open(script_path, "w") as f:
                f.write(template)

            # Update workspace with script path
            workspace_manager.update_workspace(
                workspace_info.workspace_id,
                script_path=script_path,
            )

            logger.info(f"Generated Pepper script: {script_path}")

            return {
                "workspace_id": workspace_info.workspace_id,
                "workspace_path": workspace_info.path,
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
                    "use_gpu": use_gpu,
                },
                "pepper_config": {
                    "process": process,
                    "collision_energy": collision_energy,
                    "n_events": n_events,
                    "output_format": output_format,
                    "output_file": resolved_output_file if output_format != "disabled" else None,
                    "setup_mode": "fullstack" if use_fullstack else "direct_executable",
                    "executable": resolved_pepper_executable if not use_fullstack else "(via setup.sh)",
                },
                "next_step": (
                    f"Submit job with: submit_pbs_job("
                    f"workspace_id='{workspace_info.workspace_id}', "
                    f"queue='{queue}', account='{account}')"
                ),
            }

        @mcp.tool()
        def get_pepper_info() -> Dict[str, Any]:
            """
            Get information about Pepper configuration for the current system.

            Returns system-specific settings, recommended configurations,
            and example usage for running Pepper jobs.

            Returns:
                Dictionary with system settings and recommendations
            """
            default_queue_config = system_config.get_queue(default_queue)
            max_nodes = (
                default_queue_config.max_nodes if default_queue_config else "unknown"
            )

            workspace_base = None
            if workspace_manager:
                workspace_base = str(workspace_manager.base_path)

            return {
                "application": "pepper",
                "description": self.description,
                "version": "Pepper parton-level event generator",
                "documentation": "https://spice-mc.gitlab.io/pepper/",
                "system": system_config.display_name,
                "setup_mode": "fullstack" if (fullstack_setup and pepper_setup) else "direct_executable",
                "fullstack_setup": fullstack_setup,
                "pepper_setup": pepper_setup,
                "modules": modules,
                "mpi_command": mpi_command,
                "mpi_flags": mpi_flags,
                "environment": env_vars,
                "gpu_config": {
                    "gpus_per_node": gpus_per_node,
                    "tiles_per_gpu": tiles_per_gpu,
                    "total_tiles_per_node": gpus_per_node * tiles_per_gpu,
                    "recommended_ranks_per_node": default_ranks_per_node,
                },
                "defaults": {
                    "walltime": default_walltime,
                    "queue": default_queue,
                    "pepper_executable": default_pepper_path if default_pepper_path else "(via fullstack setup)",
                    "account": default_account or "(set PBS_ACCOUNT env var)",
                },
                "workspace_base_path": workspace_base,
                "recommended_usage": {
                    "min_nodes": 1,
                    "max_nodes": max_nodes,
                    "ranks_per_node": default_ranks_per_node,
                    "description": (
                        f"Use {default_ranks_per_node} ranks per node "
                        f"(1 per GPU) for optimal GPU utilization"
                    ),
                },
                "example_processes": [
                    "ppjj",  # Predefined: p p -> j j (dijet)
                    "ppeej",  # Predefined: p p -> e+ e- j (Drell-Yan + jet)
                    'd db -> e+ e-',  # Explicit: Drell-Yan
                    'g g -> t tb',  # Explicit: top pair production
                    'u ub -> W+ W-',  # Explicit: W pair production
                ],
                "example": (
                    'build_pepper_submit_script('
                    'process="d db -> e+ e-", '
                    'collision_energy=91.2, '
                    'n_events=10000, '
                    'num_nodes=2, '
                    "account='myproject')"
                ),
            }

        @mcp.tool()
        def create_pepper_gpu_affinity_script(
            workspace_id: Optional[str] = None,
        ) -> Dict[str, Any]:
            """
            Create a GPU affinity wrapper script for Pepper.

            Generates a helper script that sets ZE_AFFINITY_MASK based on
            the local MPI rank. This is useful for custom launch configurations
            or debugging GPU binding issues.

            Args:
                workspace_id: Optional workspace ID to store the script

            Returns:
                Dictionary with script path and usage instructions
            """
            if workspace_manager is None:
                return {
                    "error": "Workspace manager not available",
                    "status": "failed",
                }

            # Get or create workspace
            if workspace_id:
                workspace_info = workspace_manager.get_workspace(workspace_id)
                if not workspace_info:
                    return {
                        "error": f"Workspace {workspace_id} not found",
                        "status": "failed",
                    }
            else:
                try:
                    workspace_info = workspace_manager.create_workspace(
                        job_name="pepper_affinity",
                        metadata={"application": "pepper", "type": "affinity_script"},
                    )
                except OSError as e:
                    return {
                        "error": f"Failed to create workspace: {e}",
                        "status": "failed",
                    }

            # Generate the affinity script
            script_content = PepperTemplates.generate_gpu_affinity_script()
            script_path = workspace_manager.get_script_path(
                workspace_info.workspace_id, "gpu_affinity.sh"
            )

            with open(script_path, "w") as f:
                f.write(script_content)

            # Make it executable
            os.chmod(script_path, 0o755)

            logger.info(f"Generated GPU affinity script: {script_path}")

            return {
                "workspace_id": workspace_info.workspace_id,
                "script_path": script_path,
                "status": "created",
                "usage": (
                    f"mpiexec -n 12 --ppn 12 {script_path} pepper --process \"...\" ..."
                ),
                "description": (
                    "This script sets ZE_AFFINITY_MASK based on local MPI rank "
                    "to bind each rank to a specific GPU tile on Aurora."
                ),
            }
