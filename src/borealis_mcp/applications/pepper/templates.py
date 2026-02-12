"""Pepper application templates for Borealis MCP.

Updated based on working Aurora submit script from pepper repository.
Uses the fullstack installation with setup.sh sourcing.
"""

from typing import Any, Dict, List, Optional

from borealis_mcp.config.system import SystemConfig


class PepperTemplates:
    """PBS submit script templates for Pepper event generator."""

    @staticmethod
    def generate_submit_script(
        system_config: SystemConfig,
        num_nodes: int,
        ranks_per_node: int,
        walltime: str,
        queue: str,
        job_name: str,
        account: str,
        modules: List[str],
        mpi_command: str,
        mpi_flags: List[str],
        env_vars: Dict[str, Any],
        pepper_executable: str,
        pepper_args: str,
        use_gpu: bool = True,
        gpu_affinity_script: Optional[str] = None,
        batch_size: int = 1024,
        cpu_bind_depth: int = 8,
        fullstack_setup: Optional[str] = None,
        pepper_setup: Optional[str] = None,
        workspace_path: Optional[str] = None,
    ) -> str:
        """
        Generate Pepper PBS submit script for Aurora.

        Creates a script optimized for running Pepper on Intel GPUs with
        proper MPI configuration and GPU affinity.

        Args:
            system_config: System configuration
            num_nodes: Number of nodes to use
            ranks_per_node: MPI ranks per node (typically 6 for Aurora, 1 per GPU)
            walltime: Wall time in HH:MM:SS format
            queue: Queue name
            job_name: Name for the PBS job
            account: PBS account/project name
            modules: List of modules to load
            mpi_command: MPI launch command (e.g., "mpiexec")
            mpi_flags: Additional MPI flags
            env_vars: Environment variables to set
            pepper_executable: Path to pepper executable (ignored if setup scripts provided)
            pepper_args: Command-line arguments for pepper
            use_gpu: Whether to enable GPU support (default True)
            gpu_affinity_script: Optional path to GPU affinity script
            batch_size: Batch size for GPU processing (default 1024)
            cpu_bind_depth: Threads per rank for cpu-bind (default 8)
            fullstack_setup: Path to fullstack setup.sh (e.g., /path/to/fullstack/setup.sh)
            pepper_setup: Path to pepper setup.sh (e.g., /path/to/fullstack/pepper/setup.sh)
            workspace_path: Path to workspace directory for logs and output

        Returns:
            Complete PBS submit script as string
        """
        # Determine if we're using fullstack setup or direct executable
        use_fullstack = fullstack_setup is not None and pepper_setup is not None

        # Use workspace_path if provided, otherwise fall back to PBS_O_WORKDIR
        if workspace_path:
            work_dir = workspace_path
            # Update pepper_args to use absolute workspace path for output
            pepper_args = pepper_args.replace('--output "', f'--output "{workspace_path}/')
        else:
            work_dir = "${PBS_O_WORKDIR}"

        if use_fullstack:
            # Use fullstack setup.sh scripts - pepper is found via PATH after sourcing
            env_setup_section = f"""# Source Pepper fullstack environment
source {fullstack_setup}
source {pepper_setup}
PEPPER_EXE=$(which pepper)"""
            pepper_exe_var = "${PEPPER_EXE}"
            verify_exe_section = f"""# --- Verify Executable -------------------------------------------------------

if [[ ! -x "${{PEPPER_EXE}}" ]]; then
    echo "ERROR: Pepper executable not found after sourcing setup scripts"
    echo "Checked: fullstack_setup={fullstack_setup}"
    echo "Checked: pepper_setup={pepper_setup}"
    exit 1
fi"""
        else:
            # Use direct executable path (legacy mode)
            # Build module load commands - include module use for /soft/modulefiles
            module_cmds = "module use /soft/modulefiles\n" + "\n".join(
                [f"module load {mod}" for mod in modules]
            )
            # Build environment variable exports
            env_cmds = "\n".join(
                [f'export {key}="{value}"' for key, value in env_vars.items()]
            )
            env_section = env_cmds if env_cmds else "# No additional environment variables"
            env_setup_section = f"""# Load modules
{module_cmds}

# Set environment variables
{env_section}"""
            pepper_exe_var = pepper_executable
            verify_exe_section = f"""# --- Verify Executable -------------------------------------------------------

if [[ ! -x "{pepper_executable}" ]]; then
    echo "ERROR: Pepper executable not found or not executable: {pepper_executable}"
    exit 1
fi"""

        # Build MPI flags string - add depth and cpu-bind for Aurora
        base_flags = [f"--depth={cpu_bind_depth}", "--cpu-bind=depth"]
        all_flags = base_flags + (mpi_flags if mpi_flags else [])
        flags_str = " ".join(all_flags)

        # Default filesystems
        default_fs = ":".join(system_config.default_filesystems)

        # Calculate total ranks
        total_ranks = num_nodes * ranks_per_node

        # Get GPU info from system config
        gpus_per_node = getattr(system_config, "gpus_per_node", 6)

        # GPU affinity setup for Aurora Intel GPUs
        # Each node has 6 GPUs - we use PALS_LOCAL_RANKID for simple affinity
        gpu_affinity_section = ""
        wrapper_creation = ""
        exec_wrapper_var = ""

        if use_gpu and ranks_per_node > 1:
            # Create wrapper script for multi-rank GPU affinity
            wrapper_creation = '''
# Create GPU affinity wrapper script
GPU_WRAPPER="${WORKSPACE_DIR}/gpu_affinity_wrapper.sh"
cat > "${GPU_WRAPPER}" << 'WRAPPER_EOF'
#!/bin/bash
# Set GPU affinity based on local MPI rank
# PALS sets PALS_LOCAL_RANKID for each rank
export ZE_AFFINITY_MASK=${PALS_LOCAL_RANKID}
exec "$@"
WRAPPER_EOF
chmod +x "${GPU_WRAPPER}"
EXEC_WRAPPER="${GPU_WRAPPER}"
'''
            exec_wrapper_var = "${EXEC_WRAPPER} "
        elif use_gpu:
            # Single rank - use all GPUs
            gpu_affinity_section = """
# Single-rank GPU setup - use all GPUs
export ZE_AFFINITY_MASK=0,1,2,3,4,5
"""
            exec_wrapper_var = ""

        # Build the mpiexec command
        if total_ranks == 1:
            run_command = f"{pepper_exe_var} {pepper_args}"
        else:
            if exec_wrapper_var:
                run_command = f"""{mpi_command} -n $NTOTRANKS \\
            -ppn $NRANKS_PER_NODE \\
            {flags_str} \\
            $EXEC_WRAPPER {pepper_exe_var} {pepper_args}"""
            else:
                run_command = f"""{mpi_command} -n $NTOTRANKS \\
            -ppn $NRANKS_PER_NODE \\
            {flags_str} \\
            {pepper_exe_var} {pepper_args}"""

        return f'''#!/bin/bash -l
#PBS -A {account}
#PBS -N {job_name}
#PBS -l select={num_nodes}
#PBS -l walltime={walltime}
#PBS -l filesystems={default_fs}
#PBS -l place=scatter
#PBS -q {queue}
#PBS -k doe

# =============================================================================
# Pepper Event Generator - Aurora PBS Submit Script
# =============================================================================
# System: {system_config.display_name}
# Total Ranks: {total_ranks} ({num_nodes} nodes x {ranks_per_node} ranks/node)
# GPU Mode: {"Enabled" if use_gpu else "Disabled"}
# Workspace: {work_dir}
# Generated by Borealis MCP
# =============================================================================

# --- Workspace and Log Directory ---------------------------------------------
# Use the workspace path for all output
WORKSPACE_DIR="{work_dir}"
LOG_DIR="${{WORKSPACE_DIR}}"

# Redirect stdout and stderr to log files in workspace
exec > "${{LOG_DIR}}/pepper_stdout.log" 2> "${{LOG_DIR}}/pepper_stderr.log"

# --- Environment Setup -------------------------------------------------------

{env_setup_section}

# --- MPI and Job Configuration -----------------------------------------------

NNODES={num_nodes}
NRANKS_PER_NODE={ranks_per_node}
NTOTRANKS={total_ranks}

# --- Job Information ---------------------------------------------------------

echo "=============================================="
echo "Pepper Aurora Job"
echo "=============================================="
echo "Job ID:          ${{PBS_JOBID}}"
echo "Job Name:        ${{PBS_JOBNAME}}"
echo "Workspace:       ${{WORKSPACE_DIR}}"
echo "Log directory:   ${{LOG_DIR}}"
echo "Nodes:           $NNODES"
echo "Ranks per node:  $NRANKS_PER_NODE"
echo "Total ranks:     $NTOTRANKS"
echo "GPUs per rank:   1 (affinity via ZE_AFFINITY_MASK)"
echo "Pepper exe:      {pepper_exe_var}"
echo "Pepper args:     {pepper_args}"
echo "=============================================="
echo ""

# Change to workspace directory
cd ${{WORKSPACE_DIR}}

{verify_exe_section}

# Print loaded modules for debugging
echo "Loaded modules:"
module list
echo ""

# --- GPU Affinity Setup ------------------------------------------------------
# Aurora uses Intel Data Center GPU Max (Ponte Vecchio)
# Each node has {gpus_per_node} GPUs
{gpu_affinity_section}
{wrapper_creation}
# --- Run Pepper --------------------------------------------------------------

echo "Starting Pepper at $(date)"
echo ""

{run_command}

EXIT_CODE=$?

echo ""
echo "Pepper finished at $(date) with exit code $EXIT_CODE"

# --- Post-run ----------------------------------------------------------------

if [[ $EXIT_CODE -eq 0 ]]; then
    echo ""
    echo "Job completed successfully!"

    # List any output files in the workspace directory
    echo ""
    echo "Output files:"
    ls -lh ${{WORKSPACE_DIR}}/*.hdf5 ${{WORKSPACE_DIR}}/*.lhe 2>/dev/null || echo "  (no HDF5 or LHE files found)"
fi

exit $EXIT_CODE
'''

    @staticmethod
    def generate_gpu_affinity_script() -> str:
        """
        Generate a standalone GPU affinity wrapper script for Aurora.

        This script can be used to wrap any executable and set the correct
        ZE_AFFINITY_MASK based on the local MPI rank. Uses the simpler
        approach of 1 GPU per rank (not tile-based).

        Returns:
            GPU affinity wrapper script as string
        """
        return '''#!/bin/bash
# GPU Affinity Wrapper Script for Aurora Intel GPUs
# Sets ZE_AFFINITY_MASK based on local MPI rank
#
# Usage: ./gpu_affinity.sh <executable> [args...]
#
# Aurora has 6 GPUs per node. This script binds each MPI rank
# to a specific GPU using PALS_LOCAL_RANKID.

# Get local rank from MPI environment
# PALS sets PALS_LOCAL_RANKID, PMI sets PMI_LOCAL_RANK
LOCAL_RANK=${PALS_LOCAL_RANKID:-${PMI_LOCAL_RANK:-0}}

# Set the affinity mask - one GPU per rank
export ZE_AFFINITY_MASK=${LOCAL_RANK}

# Debug output (uncomment for troubleshooting)
# echo "Rank $LOCAL_RANK -> GPU $LOCAL_RANK (ZE_AFFINITY_MASK=$ZE_AFFINITY_MASK)"

# Execute the command
exec "$@"
'''
