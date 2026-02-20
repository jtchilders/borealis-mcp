"""WarpX MCP application for Borealis.

WarpX is a highly-parallel particle-in-cell (PIC) code. This Borealis application
focuses on the common "python PICMI driver" workflow used on ALCF systems.

Key design points:
- User provides a run directory where inputs live and outputs are produced.
- The tool can stage/copy a driver script plus additional input files/directories
  (meshes, analysis scripts, etc.) into that run directory.
- The job script is generated automatically and is meant to be submitted via
  Borealis PBS tools. Note: PBS API submission ignores #PBS directives in the
  script; submission parameters must also be passed via submit_pbs_job.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

# Optional dependency during unit tests that only import templates.
try:
    from fastmcp import FastMCP
except ModuleNotFoundError:  # pragma: no cover
    FastMCP = Any  # type: ignore[assignment,misc]

from borealis_mcp.applications.base import ApplicationBase
from borealis_mcp.applications.warpx.templates import WarpXTemplates
from borealis_mcp.config.constants import ENV_PBS_ACCOUNT
from borealis_mcp.config.system import SystemConfig
from borealis_mcp.utils.logging import get_logger
from borealis_mcp.utils.validation import validate_account, validate_node_count, validate_walltime

if TYPE_CHECKING:
    from borealis_mcp.core.workspace import WorkspaceManager

logger = get_logger("warpx")


def _split_stage_paths(stage_paths: str) -> List[str]:
    """Parse user-provided stage paths string.

    Accepts comma-separated list. Whitespace around entries is ignored.
    """

    if not stage_paths:
        return []
    return [p.strip() for p in stage_paths.split(",") if p.strip()]


class Application(ApplicationBase):
    """WarpX application plugin."""

    @property
    def name(self) -> str:
        return "warpx"

    @property
    def description(self) -> str:
        return (
            "WarpX - PIC code. Generates PBS scripts for the Python PICMI driver workflow "
            "(driver script + CLI args), with support for staging extra input files." 
        )

    def supports_system(self, system_config: SystemConfig) -> bool:
        # Intended for ALCF systems; can be extended later.
        return system_config.name in ["aurora", "polaris", "sunspot"]

    def register_tools(
        self,
        mcp: FastMCP,
        system_config: SystemConfig,
        app_config: Optional[Dict[str, Any]] = None,
        workspace_manager: Optional["WorkspaceManager"] = None,
    ) -> None:
        # Defaults from app config
        defaults = (app_config or {}).get("defaults", {})

        modules: List[str] = (app_config or {}).get("modules", system_config.recommended_modules)
        env_vars: Dict[str, Any] = (app_config or {}).get("environment", {})

        mpi_cfg = (app_config or {}).get("mpi", {})
        mpi_command = mpi_cfg.get("command", "mpiexec")
        mpi_extra_flags: List[str] = mpi_cfg.get("flags", [])
        cpu_bind = mpi_cfg.get("cpu_bind")
        gpu_bind = mpi_cfg.get("gpu_bind")
        mpi_env_flag = mpi_cfg.get("env_flag", "-genvall")

        warpx_prefix = (app_config or {}).get("warpx_prefix")
        profile_source_default = (app_config or {}).get("profile_source")
        venv_activate_default = (app_config or {}).get("venv_activate")

        default_queue = defaults.get("queue", "debug")
        default_walltime = defaults.get("walltime", "00:30:00")
        default_filesystems = defaults.get("filesystems")
        default_job_name = defaults.get("job_name", "warpx")

        # Rank layout defaults
        default_ranks_per_node = int(defaults.get("ranks_per_node", 12))
        default_threads_per_rank = int(defaults.get("threads_per_rank", 1))

        # Default account from environment
        default_account = os.environ.get(ENV_PBS_ACCOUNT, "")

        @mcp.tool()
        def build_warpx_submit_script(
            run_dir: str,
            driver_script: str,
            driver_args: str = "",
            stage_paths: str = "",
            num_nodes: int = 1,
            ranks_per_node: int = default_ranks_per_node,
            threads_per_rank: int = default_threads_per_rank,
            account: str = default_account,
            walltime: str = default_walltime,
            queue: str = default_queue,
            job_name: str = default_job_name,
            filesystems: Optional[str] = default_filesystems,
            profile_source: Optional[str] = None,
            venv_activate: Optional[str] = None,
            workspace_id: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Generate a PBS submit script for a WarpX Python PICMI run.

            This tool treats `run_dir` as the authoritative run directory.
            All staged inputs and produced outputs/logs will reside there.

            The driver script is staged into `run_dir` and executed as:
              ./<driver_basename> <driver_args>

            Additional files/directories can be staged via `stage_paths`.

            Returns submission parameters needed by submit_pbs_job.

            Args:
                run_dir: Directory where the run will be performed (inputs/outputs).
                driver_script: Path to PICMI python driver script to stage.
                driver_args: Additional CLI args (e.g. "--dim 3 --test").
                stage_paths: Comma-separated extra files/dirs to copy into run_dir.
                num_nodes: PBS select count.
                ranks_per_node: MPI ranks per node.
                threads_per_rank: Threads per MPI rank.
                account: PBS account/project.
                walltime: PBS walltime (HH:MM:SS).
                queue: PBS queue.
                job_name: Job name.
                filesystems: PBS filesystems string (e.g. "home:flare").
                profile_source: Optional profile script to source in job.
                venv_activate: Optional python venv activate path.
                workspace_id: Optional Borealis workspace id for tracking.

            Returns:
                Dict with run_dir, script_path, workspace_id (if available), and
                submit_pbs_job parameters.
            """

            if workspace_manager is None:
                return {"error": "Workspace manager not available", "status": "failed"}

            # Validate account / walltime / node count
            try:
                account = validate_account(account)
                validate_walltime(walltime)
                validate_node_count(num_nodes)
            except Exception as e:
                return {"error": str(e), "status": "failed"}

            # Resolve run_dir and ensure it exists
            run_path = Path(run_dir).expanduser().resolve()
            try:
                run_path.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return {"error": f"Failed to create run_dir {run_path}: {e}", "status": "failed"}

            # Create/lookup a workspace for bookkeeping. We still use Borealis
            # workspace IDs, but we treat run_dir as the actual run location.
            if workspace_id:
                ws = workspace_manager.get_workspace(workspace_id)
                if not ws:
                    return {"error": f"Workspace {workspace_id} not found", "status": "failed"}
            else:
                try:
                    ws = workspace_manager.create_workspace(
                        job_name=job_name,
                        metadata={
                            "application": "warpx",
                            "run_dir": str(run_path),
                            "num_nodes": num_nodes,
                            "ranks_per_node": ranks_per_node,
                            "threads_per_rank": threads_per_rank,
                            "queue": queue,
                            "walltime": walltime,
                            "filesystems": filesystems,
                        },
                    )
                    workspace_id = ws.workspace_id
                except OSError as e:
                    return {"error": f"Failed to create workspace: {e}", "status": "failed"}

            # Stage driver script and extra paths
            driver_src = Path(driver_script).expanduser().resolve()
            if not driver_src.exists():
                return {"error": f"driver_script not found: {driver_src}", "status": "failed"}
            if not driver_src.is_file():
                return {"error": f"driver_script is not a file: {driver_src}", "status": "failed"}

            driver_dst = run_path / driver_src.name
            try:
                shutil.copy2(driver_src, driver_dst)
                # Ensure executable bit so we can run ./driver.py like in the example scripts
                driver_dst.chmod(driver_dst.stat().st_mode | 0o111)
            except OSError as e:
                return {"error": f"Failed to stage driver_script into run_dir: {e}", "status": "failed"}

            staged: List[str] = [str(driver_dst)]
            for p in _split_stage_paths(stage_paths):
                src = Path(p).expanduser().resolve()
                if not src.exists():
                    return {"error": f"stage_paths entry not found: {src}", "status": "failed"}

                dst = run_path / src.name
                try:
                    if src.is_dir():
                        if dst.exists():
                            # Avoid blowing away existing restart data; do not overwrite directories.
                            logger.info(f"Skipping stage dir {src} -> {dst} (already exists)")
                        else:
                            shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
                    staged.append(str(dst))
                except OSError as e:
                    return {"error": f"Failed to stage {src} into run_dir: {e}", "status": "failed"}

            # Determine setup sources
            resolved_profile_source = profile_source or profile_source_default
            resolved_venv_activate = venv_activate or venv_activate_default

            template = WarpXTemplates.generate_submit_script(
                system_config=system_config,
                job_name=job_name,
                account=account,
                queue=queue,
                walltime=walltime,
                filesystems=filesystems,
                run_dir=str(run_path),
                modules=modules,
                env_vars=env_vars,
                warpx_prefix=warpx_prefix,
                profile_source=resolved_profile_source,
                venv_activate=resolved_venv_activate,
                mpi_command=mpi_command,
                mpi_env_flag=mpi_env_flag,
                mpi_flags=mpi_extra_flags,
                num_nodes=num_nodes,
                ranks_per_node=ranks_per_node,
                threads_per_rank=threads_per_rank,
                driver_basename=driver_dst.name,
                driver_args=driver_args,
                cpu_bind=cpu_bind,
                gpu_bind=gpu_bind,
            )

            # Write submit script into run directory (Variant A)
            script_path = run_path / "submit.sh"
            try:
                script_path.write_text(template)
                script_path.chmod(script_path.stat().st_mode | 0o111)
            except OSError as e:
                return {"error": f"Failed to write submit script: {e}", "status": "failed"}

            # Record script path and metadata for PBS submission
            workspace_manager.update_workspace(
                workspace_id,
                script_path=str(script_path),
                metadata={
                    **(ws.metadata or {}),
                    "run_dir": str(run_path),
                    "driver_script": driver_dst.name,
                    "driver_args": driver_args,
                    "staged": staged,
                    "num_nodes": num_nodes,
                    "ranks_per_node": ranks_per_node,
                    "threads_per_rank": threads_per_rank,
                    "queue": queue,
                    "walltime": walltime,
                    "filesystems": filesystems,
                    "job_name": job_name,
                },
            )

            logger.info(f"Generated WarpX submit script: {script_path}")

            return {
                "status": "created",
                "application": "warpx",
                "workspace_id": workspace_id,
                "run_dir": str(run_path),
                "script_path": str(script_path),
                "staged": staged,
                "submission": {
                    "queue": queue,
                    "walltime": walltime,
                    "select_spec": str(num_nodes),
                    "filesystems": filesystems,
                    "account": account,
                    "job_name": job_name,
                },
                "mpi": {
                    "command": mpi_command,
                    "num_nodes": num_nodes,
                    "ranks_per_node": ranks_per_node,
                    "total_ranks": num_nodes * ranks_per_node,
                    "threads_per_rank": threads_per_rank,
                    "cpu_bind": cpu_bind,
                    "gpu_bind": gpu_bind,
                },
            }

        @mcp.tool()
        def get_warpx_info() -> Dict[str, Any]:
            """Return WarpX configuration details for the current system."""

            workspace_base = None
            if workspace_manager:
                workspace_base = str(workspace_manager.base_path)

            return {
                "application": "warpx",
                "description": self.description,
                "system": system_config.display_name,
                "defaults": {
                    "queue": default_queue,
                    "walltime": default_walltime,
                    "filesystems": default_filesystems,
                    "job_name": default_job_name,
                    "ranks_per_node": default_ranks_per_node,
                    "threads_per_rank": default_threads_per_rank,
                    "account": default_account or "(set PBS_ACCOUNT env var)",
                },
                "warpx_prefix": warpx_prefix,
                "profile_source": profile_source_default,
                "venv_activate": venv_activate_default,
                "modules": modules,
                "environment": env_vars,
                "mpi": {
                    "command": mpi_command,
                    "env_flag": mpi_env_flag,
                    "flags": mpi_extra_flags,
                    "cpu_bind": cpu_bind,
                    "gpu_bind": gpu_bind,
                },
                "workspace_base_path": workspace_base,
                "example": (
                    "build_warpx_submit_script("
                    "run_dir='/lus/flare/projects/<proj>/runs/case1', "
                    "driver_script='/path/to/inputs_case.py', "
                    "driver_args='--dim 3 --test', "
                    "stage_paths='/path/to/mesh.h5,/path/to/analysis.py', "
                    "num_nodes=1, account='<proj>')"
                ),
            }
