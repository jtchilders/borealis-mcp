"""Core PBS MCP prompts for Borealis."""

from fastmcp import FastMCP

from borealis_mcp.config.system import SystemConfig
from borealis_mcp.utils.logging import get_logger

logger = get_logger("pbs_prompts")


def register_pbs_prompts(mcp: FastMCP, system_config: SystemConfig) -> None:
    """
    Register core PBS prompts with the MCP server.

    Args:
        mcp: FastMCP server instance
        system_config: Current system configuration
    """
    default_queue = system_config.get_default_queue()
    default_queue_name = default_queue.name if default_queue else "debug"
    default_fs = ":".join(system_config.default_filesystems)

    @mcp.prompt()
    def submit_job_workflow() -> str:
        """
        Guide for submitting a PBS job on the current system.

        Returns step-by-step instructions for job submission.
        """
        return f"""# Job Submission Workflow for {system_config.display_name}

## Prerequisites
1. Ensure PBS_ACCOUNT environment variable is set to your project allocation
2. Have a submit script ready or use an application-specific tool to generate one

## Steps

### 1. Check System Status
Use `get_system_info()` to verify system configuration and available queues.

### 2. Check Queue Status
Use `get_queue_info()` to see current queue states and job counts.

### 3. Prepare Submit Script
Either:
- Use an application tool like `build_hello_world_submit_script()` or `build_generic_submit_script()`
- Create your own script with required PBS directives:

```bash
#!/bin/bash -l
#PBS -l select=<nodes>:ncpus={system_config.cores_per_node}
#PBS -l walltime=HH:MM:SS
#PBS -l filesystems={default_fs}
#PBS -q {default_queue_name}
#PBS -A $PBS_ACCOUNT
#PBS -N job_name

cd $PBS_O_WORKDIR
# Your commands here
```

### 4. Submit the Job
Use `submit_pbs_job(script_path="/path/to/script.sh")` to submit.

### 5. Monitor Job Status
Use `get_job_status(job_id="<job_id>")` to check progress.

## Common Queues
{"".join(f"- **{q.name}**: max {q.max_nodes} nodes, {q.max_walltime} walltime\n" for q in system_config.queues.values())}

## Tips
- Start with the debug queue for testing
- Use smaller node counts for faster scheduling
- Check `list_jobs()` to see your current jobs
"""

    @mcp.prompt()
    def debug_job() -> str:
        """
        Guide for debugging a PBS job.

        Returns troubleshooting steps for common job issues.
        """
        return f"""# Job Debugging Guide for {system_config.display_name}

## Check Job Status
1. Use `get_job_status(job_id="<job_id>")` to see current state
2. Look at the state_description for details

## Common States
- **Q (Queued)**: Job is waiting for resources
- **R (Running)**: Job is executing
- **H (Held)**: Job is held (use `release_job()` to release)
- **E (Exiting)**: Job is finishing up

## If Job Won't Start (Stuck in Q)
1. Check if resources are available: `get_queue_info()`
2. Verify your select specification matches available nodes
3. Check walltime isn't too long for the queue
4. Verify filesystems are correct: `{default_fs}`

## If Job Failed
1. Check exit_status in job info
2. Look at the output files (default: <job_name>.o<job_number>)
3. Look at the error files (default: <job_name>.e<job_number>)

## Common Issues
- **Account not valid**: Ensure PBS_ACCOUNT is set correctly
- **Queue not available**: Check queue is enabled with `get_queue_info()`
- **Filesystem not mounted**: Verify filesystems in your script
- **Walltime exceeded**: Job ran longer than requested time

## Cancel a Problematic Job
Use `delete_job(job_id="<job_id>")` or `delete_job(job_id="<job_id>", force=True)` for running jobs.
"""

    @mcp.prompt()
    def system_overview() -> str:
        """
        Overview of the current HPC system.

        Returns system capabilities and configuration summary.
        """
        return f"""# {system_config.display_name} System Overview

## Facility
{system_config.facility}

## Hardware Summary
- **{system_config.total_nodes}** compute nodes
- **{system_config.cores_per_node}** CPU cores per node ({system_config.cpu_model})
- **{system_config.gpus_per_node}** GPUs per node ({system_config.gpu_type})
- **{system_config.memory_per_node} GB** memory per node ({system_config.memory_type})
- **{system_config.interconnect}** interconnect

## Available Queues
{"".join(f"- **{q.name}**: up to {q.max_nodes} nodes, {q.max_walltime} max walltime ({q.description})\n" for q in system_config.queues.values())}

## Filesystems
{"".join(f"- **{name}**: `{path}`\n" for name, path in system_config.filesystems.items())}
Default for jobs: `{default_fs}`

## Recommended Modules
```bash
{"".join(f"module load {mod}\n" for mod in system_config.recommended_modules)}```

## Getting Started
1. Set your project: `export PBS_ACCOUNT=your_project`
2. Use `get_system_info()` for detailed configuration
3. Use application-specific tools to generate submit scripts
4. Submit with `submit_pbs_job()`
"""
