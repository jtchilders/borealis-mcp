"""Core PBS MCP resources for Borealis."""

from fastmcp import FastMCP

from borealis_mcp.config.system import SystemConfig, SystemConfigLoader
from borealis_mcp.core.pbs_client import get_pbs_client, get_pbs_exception_class
from borealis_mcp.utils.logging import get_logger

logger = get_logger("pbs_resources")


def register_pbs_resources(
    mcp: FastMCP, system_config: SystemConfig, config_loader: SystemConfigLoader
) -> None:
    """
    Register core PBS resources with the MCP server.

    Args:
        mcp: FastMCP server instance
        system_config: Current system configuration
        config_loader: System configuration loader
    """
    PBSException = get_pbs_exception_class()

    @mcp.resource("pbs://system/current")
    def get_current_system() -> str:
        """Get current system configuration as markdown."""
        default_queue = system_config.get_default_queue()

        lines = [
            f"# {system_config.display_name}",
            "",
            f"**Facility:** {system_config.facility}",
            f"**PBS Server:** {system_config.pbs_server}",
            "",
            "## Hardware",
            f"- Total Nodes: {system_config.total_nodes}",
            f"- Cores per Node: {system_config.cores_per_node}",
            f"- GPUs per Node: {system_config.gpus_per_node}",
            f"- GPU Type: {system_config.gpu_type}",
            f"- Memory per Node: {system_config.memory_per_node} GB",
            f"- CPU Model: {system_config.cpu_model}",
            f"- Interconnect: {system_config.interconnect}",
            "",
            "## Queues",
        ]

        for queue_name, queue in system_config.queues.items():
            is_default = " (default)" if default_queue and queue_name == default_queue.name else ""
            lines.append(f"### {queue_name}{is_default}")
            lines.append(f"- Max Walltime: {queue.max_walltime}")
            lines.append(f"- Max Nodes: {queue.max_nodes}")
            if queue.description:
                lines.append(f"- Description: {queue.description}")
            lines.append("")

        lines.extend(
            [
                "## Filesystems",
                f"Default: {':'.join(system_config.default_filesystems)}",
                "",
            ]
        )
        for name, path in system_config.filesystems.items():
            lines.append(f"- {name}: `{path}`")

        lines.extend(
            [
                "",
                "## Recommended Modules",
                "```bash",
            ]
        )
        for mod in system_config.recommended_modules:
            lines.append(f"module load {mod}")
        lines.append("```")

        return "\n".join(lines)

    @mcp.resource("pbs://systems/all")
    def list_all_systems() -> str:
        """List all available system configurations."""
        system_names = config_loader.list_available_systems()

        lines = ["# Available HPC Systems", ""]
        for name in system_names:
            try:
                config = config_loader.load_system(name)
                current = " (CURRENT)" if name == system_config.name else ""
                lines.append(f"## {config.display_name}{current}")
                lines.append(f"- Name: {name}")
                lines.append(f"- Facility: {config.facility}")
                lines.append(f"- Nodes: {config.total_nodes}")
                lines.append(f"- GPUs/Node: {config.gpus_per_node}")
                lines.append(f"- GPU Type: {config.gpu_type}")
                lines.append("")
            except Exception as e:
                lines.append(f"## {name} (error loading: {e})")
                lines.append("")

        return "\n".join(lines)

    @mcp.resource("pbs://queues")
    def get_queues_resource() -> str:
        """Get queue information as markdown."""
        lines = [f"# Queues on {system_config.display_name}", ""]

        try:
            with get_pbs_client(system_config) as pbs:
                queues = pbs.stat_queues()
                for q in queues:
                    lines.append(f"## {q.name}")
                    lines.append(f"- Enabled: {q.attrs.get('enabled', 'unknown')}")
                    lines.append(f"- Started: {q.attrs.get('started', 'unknown')}")
                    lines.append(f"- Total Jobs: {q.attrs.get('total_jobs', '0')}")
                    lines.append(
                        f"- Max Walltime: {q.attrs.get('resources_max.walltime', 'unknown')}")
                    lines.append(
                        f"- Max Nodes: {q.attrs.get('resources_max.nodect', 'unknown')}")
                    lines.append("")
        except PBSException as e:
            lines.append(f"Error fetching queue info: {e}")

        return "\n".join(lines)

    @mcp.resource("pbs://jobs/summary")
    def get_jobs_summary() -> str:
        """Get summary of current jobs as markdown."""
        lines = [f"# Job Summary on {system_config.display_name}", ""]

        try:
            with get_pbs_client(system_config) as pbs:
                jobs = pbs.stat_jobs()

                # Count by state
                states = {}
                for job in jobs:
                    state = job.attrs.get("job_state", "unknown")
                    states[state] = states.get(state, 0) + 1

                lines.append("## By State")
                state_names = {
                    "Q": "Queued",
                    "R": "Running",
                    "H": "Held",
                    "E": "Exiting",
                    "F": "Finished",
                }
                for state, count in sorted(states.items()):
                    name = state_names.get(state, state)
                    lines.append(f"- {name} ({state}): {count}")

                lines.extend(["", f"**Total Jobs:** {len(jobs)}"])

        except PBSException as e:
            lines.append(f"Error fetching job info: {e}")

        return "\n".join(lines)

    @mcp.resource("pbs://filesystems")
    def get_filesystems_resource() -> str:
        """Get filesystem information as markdown."""
        lines = [
            f"# Filesystems on {system_config.display_name}",
            "",
            f"**Default:** {':'.join(system_config.default_filesystems)}",
            "",
            "## Available Filesystems",
        ]

        for name, path in system_config.filesystems.items():
            is_default = " (default)" if name in system_config.default_filesystems else ""
            lines.append(f"- **{name}**{is_default}: `{path}`")

        lines.extend(
            [
                "",
                "## Usage in PBS",
                "Specify filesystems in your job script:",
                "```bash",
                f"#PBS -l filesystems={':'.join(system_config.default_filesystems)}",
                "```",
            ]
        )

        return "\n".join(lines)
