"""Discovery tools for Borealis MCP.

Provides tools for agents to discover available applications,
tools, and system capabilities.
"""

from typing import Any, Dict

from fastmcp import FastMCP

from borealis_mcp.applications.registry import ApplicationRegistry
from borealis_mcp.config.system import SystemConfig, SystemConfigLoader
from borealis_mcp.utils.logging import get_logger

logger = get_logger("discovery")


def register_discovery_tools(
    mcp: FastMCP,
    system_config: SystemConfig,
    config_loader: SystemConfigLoader,
    registry: ApplicationRegistry,
) -> None:
    """
    Register discovery tools with the MCP server.

    These tools help agents understand what capabilities are available
    and how to use them.

    Args:
        mcp: FastMCP server instance
        system_config: Current system configuration
        config_loader: Configuration loader
        registry: Application registry with discovered apps
    """

    @mcp.tool()
    def get_borealis_info() -> Dict[str, Any]:
        """
        Get comprehensive information about Borealis MCP capabilities.

        This is the primary discovery tool for agents. Returns information
        about the current system, available applications, and quick-start
        guidance.

        Returns:
            Dictionary with system info, applications, and usage guidance
        """
        # Get application info
        apps_info = []
        for app_name in registry.list_applications():
            app = registry.get_application(app_name)
            if app and app.supports_system(system_config):
                apps_info.append({
                    "name": app.name,
                    "description": app.description,
                    "supported": True,
                })

        # Get available systems
        available_systems = config_loader.list_available_systems()

        return {
            "service": "Borealis MCP",
            "version": "0.1.0",
            "description": (
                "AI agent interface for ALCF supercomputers. "
                "Provides tools for building and submitting PBS jobs, "
                "managing workspaces, and running scientific applications."
            ),
            "current_system": {
                "name": system_config.name,
                "display_name": system_config.display_name,
                "facility": system_config.facility,
                "gpus_per_node": system_config.gpus_per_node,
                "cores_per_node": system_config.cores_per_node,
            },
            "available_systems": available_systems,
            "applications": apps_info,
            "core_tools": [
                {
                    "category": "PBS Job Management",
                    "tools": [
                        "submit_pbs_job - Submit a PBS job script",
                        "get_job_status - Check status of a job",
                        "list_jobs - List PBS jobs with filtering",
                        "cancel_job - Cancel a running or queued job",
                        "get_job_output - Get stdout/stderr from a job",
                    ],
                },
                {
                    "category": "Workspace Management",
                    "tools": [
                        "create_job_workspace - Create a directory for job files",
                        "get_workspace_info - Get workspace details",
                        "list_workspaces - List existing workspaces",
                        "cleanup_workspace - Remove a workspace",
                    ],
                },
                {
                    "category": "Script Generation",
                    "tools": [
                        "build_generic_submit_script - Build PBS script for any executable",
                        "build_pepper_submit_script - Build PBS script for Pepper event generator",
                        "build_hello_world_submit_script - Build simple test script",
                    ],
                },
                {
                    "category": "Discovery",
                    "tools": [
                        "get_borealis_info - This tool: overview of all capabilities",
                        "list_available_applications - List apps with details",
                        "get_current_system_details - Detailed current system info",
                    ],
                },
            ],
            "resources": [
                "pbs://system/current - Current system configuration",
                "pbs://systems/all - All available HPC systems",
                "pbs://queues - Queue information",
                "pbs://jobs/summary - Job summary",
                "pbs://filesystems - Filesystem information",
            ],
            "quick_start": {
                "step_1": "Call get_borealis_info() to understand available capabilities",
                "step_2": "Call list_available_applications() to see app-specific tools",
                "step_3": "Use build_*_submit_script() to generate a PBS script",
                "step_4": "Use submit_pbs_job() to submit the job",
                "step_5": "Use get_job_status() to monitor progress",
            },
            "example_workflow": (
                "To run Pepper on Aurora:\n"
                "1. get_pepper_info() - See configuration and examples\n"
                "2. build_pepper_submit_script(process='ppjj', collision_energy=13000, "
                "n_events=10000, num_nodes=2, pepper_executable='/path/to/pepper')\n"
                "3. submit_pbs_job(workspace_id='...', account='myproject')\n"
                "4. get_job_status(job_id='...')"
            ),
        }

    @mcp.tool()
    def list_available_applications() -> Dict[str, Any]:
        """
        List all available applications with detailed information.

        Returns information about each registered application including
        description, supported systems, and available tools.

        Returns:
            Dictionary with list of applications and their details
        """
        applications = []

        for app_name in registry.list_applications():
            app = registry.get_application(app_name)
            if not app:
                continue

            supported = app.supports_system(system_config)

            # Load app-specific config if available
            app_config = config_loader.load_app_config(app_name, system_config.name)

            app_info = {
                "name": app.name,
                "description": app.description,
                "supported_on_current_system": supported,
                "has_custom_config": app_config is not None,
            }

            # Add app-specific tool hints based on known apps
            if app.name == "pepper":
                app_info["tools"] = [
                    "build_pepper_submit_script - Generate PBS script for Pepper",
                    "get_pepper_info - Get Pepper configuration and examples",
                    "create_pepper_gpu_affinity_script - Create GPU affinity wrapper",
                ]
                app_info["info_tool"] = "get_pepper_info()"
            elif app.name == "generic":
                app_info["tools"] = [
                    "build_generic_submit_script - Generate PBS script for any executable",
                ]
            elif app.name == "hello_world":
                app_info["tools"] = [
                    "build_hello_world_submit_script - Generate simple test script",
                ]

            applications.append(app_info)

        return {
            "current_system": system_config.name,
            "applications": applications,
            "total_count": len(applications),
            "supported_count": sum(
                1 for a in applications if a["supported_on_current_system"]
            ),
        }

    @mcp.tool()
    def get_current_system_details() -> Dict[str, Any]:
        """
        Get detailed information about the current HPC system.

        Returns comprehensive system configuration including hardware,
        queues, filesystems, and recommended settings.

        Returns:
            Dictionary with complete system configuration
        """
        # Get queue info
        queues_info = {}
        for queue_name, queue in system_config.queues.items():
            queues_info[queue_name] = {
                "max_walltime": queue.max_walltime,
                "max_nodes": queue.max_nodes,
                "description": queue.description,
            }

        # Get custom settings
        custom = getattr(system_config, "custom_settings", {}) or {}

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
            "queues": queues_info,
            "filesystems": system_config.filesystems,
            "default_filesystems": system_config.default_filesystems,
            "recommended_modules": system_config.recommended_modules,
            "mpi_settings": custom.get("mpi", {}),
            "gpu_settings": custom.get("gpu", {}),
            "environment": custom.get("environment", {}),
        }

    logger.info("Registered discovery tools")
