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

import json
import os
import shutil
import subprocess
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


# ---------------------------------------------------------------------------
# warpx-inputgen integration helpers
# ---------------------------------------------------------------------------

# Maps sim_type → (gen CLI subcommand, validate CLI subcommand, default dim)
_SIM_TYPES: Dict[str, tuple] = {
    "electrostatic_plasma":   ("gen-electrostatic-plasma-native",   "validate-electrostatic-plasma",   1),
    "hybrid_plasma":          ("gen-hybrid-plasma-native",          "validate-hybrid-plasma",           1),
    "ion_beam_instability":   ("gen-ion-beam-instability-native",   "validate-ion-beam-instability",   1),
    "laser_acceleration":     ("gen-laser-acceleration-native",     "validate-laser-acceleration",     2),
    "magnetic_reconnection":  ("gen-magnetic-reconnection-native",  "validate-magnetic-reconnection",  2),
    "pwfa":                   ("gen-pwfa-native",                   "validate-pwfa",                   2),
    "uniform_plasma":         ("gen-uniform-plasma-native",         "validate-uniform-plasma",         3),
    "electromagnetic_pic":    ("gen-electromagnetic-pic-native",    "validate-electromagnetic-pic",    2),
    "electrostatic_pic":      ("gen-electrostatic-pic-native",      "validate-electrostatic-pic",      1),
}


def _find_inputgen_bin(inputgen_bin: Optional[str], venv_activate: Optional[str]) -> Optional[str]:
    """Locate the warpx-inputgen entry-point script.

    Search order:
    1. ``inputgen_bin`` config key (explicit path).
    2. Derived from ``venv_activate``: same bin/ directory, name warpx-inputgen.
    3. PATH via shutil.which.

    Returns the resolved path string, or None if not found.
    """
    if inputgen_bin:
        p = Path(os.path.expandvars(os.path.expanduser(inputgen_bin)))
        if p.exists():
            return str(p)

    if venv_activate:
        derived = (
            Path(os.path.expandvars(os.path.expanduser(venv_activate))).parent
            / "warpx-inputgen"
        )
        if derived.exists():
            return str(derived)

    return shutil.which("warpx-inputgen")


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

        # Native binary mode config
        warpx_bin_dir: Optional[str] = (app_config or {}).get("warpx_bin_dir")
        ld_library_path_prepend: List[str] = (app_config or {}).get("ld_library_path_prepend", [])

        # inputgen: optional explicit path to warpx-inputgen binary;
        # falls back to derivation from venv_activate, then PATH.
        inputgen_bin_default: Optional[str] = (app_config or {}).get("inputgen_bin")

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
        def build_warpx_native_submit_script(
            run_dir: str,
            inputs_file: str,
            dim: int = 1,
            cli_overrides: str = "",
            num_nodes: int = 1,
            ranks_per_node: int = default_ranks_per_node,
            threads_per_rank: int = default_threads_per_rank,
            account: str = default_account,
            walltime: str = default_walltime,
            queue: str = default_queue,
            job_name: str = default_job_name,
            filesystems: Optional[str] = default_filesystems,
            profile_source: Optional[str] = None,
            workspace_id: Optional[str] = None,
        ) -> Dict[str, Any]:
            """Generate a PBS submit script for a WarpX native binary run.

            The native WarpX binary is located automatically by scanning
            `warpx_bin_dir` (from aurora.yaml) for a file matching
            `warpx.{dim}d.*`.  No Python driver or venv is needed.

            The inputs file (a WarpX AMReX ParmParse file, typically generated
            by `warpx-inputgen`) is staged into `run_dir` and referenced by
            name when the binary is invoked.

            Args:
                run_dir: Directory where the run will be performed.
                inputs_file: Path to the WarpX ParmParse inputs file to stage.
                dim: Simulation dimensionality (1, 2, or 3).  Used to select
                    the correct binary variant (warpx.{dim}d.*).
                cli_overrides: Additional ParmParse key=value overrides appended
                    to the mpiexec command line (e.g. "max_step=10 warpx.verbose=2").
                num_nodes: PBS select count.
                ranks_per_node: MPI ranks per node.
                threads_per_rank: Threads per MPI rank.
                account: PBS account/project.
                walltime: PBS walltime (HH:MM:SS).
                queue: PBS queue.
                job_name: Job name.
                filesystems: PBS filesystems string (e.g. "home:flare").
                profile_source: Optional profile script to source in job.
                workspace_id: Optional Borealis workspace id for tracking.

            Returns:
                Dict with run_dir, script_path, workspace_id (if available), and
                submit_pbs_job parameters.
            """
            if workspace_manager is None:
                return {"error": "Workspace manager not available", "status": "failed"}

            if not warpx_bin_dir:
                return {
                    "error": (
                        "warpx_bin_dir is not configured in aurora.yaml. "
                        "Add 'warpx_bin_dir: /path/to/warpx/bin' to the WarpX app config."
                    ),
                    "status": "failed",
                }

            try:
                account = validate_account(account)
                validate_walltime(walltime)
                validate_node_count(num_nodes)
            except Exception as e:
                return {"error": str(e), "status": "failed"}

            if dim not in (1, 2, 3):
                return {"error": f"dim must be 1, 2, or 3; got {dim}", "status": "failed"}

            run_path = Path(run_dir).expanduser().resolve()
            try:
                run_path.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return {"error": f"Failed to create run_dir {run_path}: {e}", "status": "failed"}

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
                            "run_mode": "native",
                            "run_dir": str(run_path),
                            "dim": dim,
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

            # Stage inputs file into run directory
            inputs_src = Path(inputs_file).expanduser().resolve()
            if not inputs_src.exists():
                return {"error": f"inputs_file not found: {inputs_src}", "status": "failed"}
            if not inputs_src.is_file():
                return {"error": f"inputs_file is not a file: {inputs_src}", "status": "failed"}

            inputs_dst = run_path / inputs_src.name
            if inputs_src.resolve() != inputs_dst.resolve():
                try:
                    shutil.copy2(inputs_src, inputs_dst)
                except OSError as e:
                    return {"error": f"Failed to stage inputs_file into run_dir: {e}", "status": "failed"}

            resolved_profile_source = profile_source or profile_source_default

            template = WarpXTemplates.generate_native_submit_script(
                system_config=system_config,
                job_name=job_name,
                account=account,
                queue=queue,
                walltime=walltime,
                filesystems=filesystems,
                run_dir=str(run_path),
                modules=modules,
                env_vars=env_vars,
                ld_library_path_prepend=ld_library_path_prepend,
                profile_source=resolved_profile_source,
                warpx_bin_dir=warpx_bin_dir,
                dim=dim,
                mpi_command=mpi_command,
                mpi_env_flag=mpi_env_flag,
                mpi_flags=mpi_extra_flags,
                num_nodes=num_nodes,
                ranks_per_node=ranks_per_node,
                threads_per_rank=threads_per_rank,
                inputs_basename=inputs_dst.name,
                cli_overrides=cli_overrides,
                cpu_bind=cpu_bind,
                gpu_bind=gpu_bind,
            )

            script_path = run_path / "submit.sh"
            try:
                script_path.write_text(template)
                script_path.chmod(script_path.stat().st_mode | 0o111)
            except OSError as e:
                return {"error": f"Failed to write submit script: {e}", "status": "failed"}

            workspace_manager.update_workspace(
                workspace_id,
                script_path=str(script_path),
                metadata={
                    **(ws.metadata or {}),
                    "run_dir": str(run_path),
                    "inputs_file": inputs_dst.name,
                    "dim": dim,
                    "cli_overrides": cli_overrides,
                    "num_nodes": num_nodes,
                    "ranks_per_node": ranks_per_node,
                    "threads_per_rank": threads_per_rank,
                    "queue": queue,
                    "walltime": walltime,
                    "filesystems": filesystems,
                    "job_name": job_name,
                },
            )

            logger.info(f"Generated WarpX native submit script: {script_path}")

            return {
                "status": "created",
                "application": "warpx",
                "run_mode": "native",
                "workspace_id": workspace_id,
                "run_dir": str(run_path),
                "script_path": str(script_path),
                "inputs_file": str(inputs_dst),
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
        def generate_warpx_inputs(
            sim_type: str,
            spec: Dict[str, Any],
            out_dir: str,
            output_filename: str = "inputs",
            validate_only: bool = False,
        ) -> Dict[str, Any]:
            """Generate a WarpX native inputs file from a simulation spec dict.

            Uses warpx-inputgen to validate and generate a WarpX ParmParse
            inputs file from a high-level simulation specification.  The
            resulting inputs file can be passed directly to
            build_warpx_native_submit_script as the inputs_file argument.

            Supported sim_type values:
            - "electrostatic_plasma"  — 1D/2D/3D ES-PIC with Poisson solver; optional EB
            - "hybrid_plasma"         — 1D/2D/3D hybrid-PIC (kinetic ions + fluid electrons)
            - "ion_beam_instability"  — 1D/2D/3D two-species hybrid-PIC beam R-instability
            - "laser_acceleration"    — 2D/3D LWFA with Gaussian laser pulse
            - "magnetic_reconnection" — 2D hybrid-PIC Harris-sheet reconnection
            - "pwfa"                  — 2D/3D beam-driven PWFA with moving window
            - "uniform_plasma"        — 3D uniform plasma (electrons + background ions)

            All fields in spec are optional; omitted values use warpx-inputgen
            defaults.  Key parameters by sim_type:

            electrostatic_plasma: dim, number_of_cells, lower_bound, upper_bound,
              field_bc, max_steps, n0 (m⁻³), Te (eV), ion_mass_amu, ppc, diag_period.
              Optional EB: eb_implicit_function, eb_potential, stl_file.

            hybrid_plasma: dim, number_of_cells, lower_bound, upper_bound,
              field_bc, max_steps, Te, n0_ref, substeps, ion_density,
              ion_mass_amu, ion_temperature_eV, ppc, B0 ([Bx,By,Bz] T),
              const_dt, resistivity, diag_period.

            ion_beam_instability: same domain/solver/ohm keys as hybrid_plasma
              plus core_density, core_mass_amu, core_temperature_eV, core_ppc,
              beam_density, beam_mass_amu, beam_temperature_eV, beam_ppc,
              beam_drift_velocity (m/s), core_drift_velocity (0=auto), B0, const_dt.

            laser_acceleration: dim, number_of_cells, lower_bound, upper_bound,
              field_bc, max_steps, cfl, plasma_density, plasma_zmin, plasma_zmax,
              wavelength (m), a0, waist (m), duration (s), focal_position_z,
              centroid_position_z, diag_period.
              Implicit solver: implicit_enabled=true, implicit_const_dt,
              implicit_theta, implicit_solver_type, implicit_max_iters.

            magnetic_reconnection: dim (default 2), number_of_cells,
              lower_bound, upper_bound, field_bc, max_steps, Te, n0_ref,
              substeps, ion_density, ion_mass_amu, ion_temperature_eV, ppc,
              B0 (scalar T), Bg (guide field T), delta (sheet half-width m),
              dB_fraction (perturbation fraction), const_dt.

            pwfa: dim (default 2), number_of_cells, lower_bound, upper_bound,
              field_bc, max_steps, cfl, plasma_density, plasma_zmin, plasma_zmax,
              driver_x_rms, driver_y_rms, driver_z_rms, driver_z_cut,
              driver_uz_m, driver_uz_th, driver_q_tot, driver_z_mean,
              driver_n_macro, moving_window (bool).
              Optional witness: witness_x_rms, witness_y_rms, witness_z_rms,
              witness_z_cut, witness_uz_m, witness_uz_th, witness_q_tot,
              witness_z_mean, witness_n_macro.

            uniform_plasma: dim (default 3), number_of_cells, lower_bound,
              upper_bound, field_bc, max_steps, cfl, plasma_density,
              B0 ([Bx,By,Bz] T), diag_period.

            electromagnetic_pic: General multi-species EM-PIC.  Domain keys:
              dim, number_of_cells, lower_bound, upper_bound, field_bc.
              Solver keys: max_steps, cfl, maxwell_solver (yee/ckc/psatd/none),
              particle_pusher (boris/vay/higuera), current_deposition.
              Optional asymmetric BCs: field_bc_lo, field_bc_hi (lists of len dim).
              species: nested list of dicts — each dict has name, charge (q_e units),
                mass_amu, injection_style, density, ppc, temperature_eV,
                xmin/xmax/ymin/ymax/zmin/zmax (slab bounds), and optional physics:
                do_field_ionization, physical_element, ionization_initial_level,
                ionization_product_species; do_qed_breit_wheeler, qed_bw_ele_product,
                qed_bw_pos_product; do_qed_quantum_sync, qed_qs_phot_product;
                do_classical_radiation_reaction; injection_style="none" for products.
              collisions: nested list of dicts — name, type (coulomb/nuclearfusion),
                species (2 names), CoulombLog (0=auto); for nuclearfusion:
                product_species, event_multiplier (1e10–1e18), probability_target_value.
              Optional laser: wavelength, a0, waist, duration, focal_position_z,
                centroid_position_z, laser_direction, laser_polarization.
              Optional: moving_window (bool), moving_window_direction.
              Optional implicit EM: implicit_enabled=true, implicit_const_dt,
                implicit_theta, implicit_solver_type, implicit_max_iters.
              Optional EB: eb_implicit_function, eb_potential, stl_file.
              Optional ext_bfield: Bx_expression, By_expression, Bz_expression.
              diag_period, diag_fields.

            electrostatic_pic: General multi-species ES-PIC (Poisson solver, no EM waves).
              Same domain keys as electromagnetic_pic.
              Solver keys: max_steps, const_dt (required), poisson_solver (multigrid/fft),
                particle_pusher (boris/vay), electrostatic_mode (labframe/relativistic),
                poisson_precision.
              species and collisions: same format as electromagnetic_pic.
              Optional EB, ext_bfield: same keys as electromagnetic_pic.
              diag_period, diag_fields.

            Args:
                sim_type: Simulation family (see above).
                spec: Flat dict of simulation parameters.
                out_dir: Directory where the inputs file will be written.
                output_filename: Name of the generated inputs file (default: "inputs").
                validate_only: If True, validate spec without writing inputs.

            Returns:
                Dict with ok (bool), inputs_path (str, if generated), issues
                (list), and any other fields from warpx-inputgen output.
            """
            if sim_type not in _SIM_TYPES:
                return {
                    "ok": False,
                    "error": f"Unknown sim_type {sim_type!r}. Must be one of: {sorted(_SIM_TYPES)}",
                }

            gen_cmd, val_cmd, default_dim = _SIM_TYPES[sim_type]

            inputgen_bin = _find_inputgen_bin(inputgen_bin_default, venv_activate_default)
            if not inputgen_bin:
                return {
                    "ok": False,
                    "error": (
                        "warpx-inputgen not found.  "
                        "It is provided by pywarpx — ensure pywarpx is installed in "
                        "the WarpX science venv (venv_activate in the WarpX YAML).  "
                        "Alternatively set inputgen_bin explicitly in the YAML."
                    ),
                }

            out_path = Path(out_dir).expanduser().resolve()
            try:
                out_path.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return {"ok": False, "error": f"Failed to create out_dir {out_path}: {e}"}

            spec_file = out_path / "_inputgen_spec.json"
            try:
                spec_file.write_text(json.dumps(spec, indent=2))
            except OSError as e:
                return {"ok": False, "error": f"Failed to write spec: {e}"}

            try:
                if validate_only:
                    cmd = [inputgen_bin, val_cmd, str(spec_file)]
                else:
                    inputs_out = out_path / output_filename
                    cmd = [inputgen_bin, gen_cmd, str(spec_file), "--out", str(inputs_out)]

                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                except subprocess.TimeoutExpired:
                    return {"ok": False, "error": "warpx-inputgen timed out after 60 s"}
                except OSError as e:
                    return {"ok": False, "error": f"Failed to run warpx-inputgen: {e}"}

                try:
                    data = json.loads(result.stdout)
                except Exception:
                    data = {
                        "ok": result.returncode == 0,
                        "raw_stdout": result.stdout[:2000],
                    }

                if result.returncode != 0 and result.stderr:
                    data.setdefault("stderr", result.stderr[:1000])

                if not validate_only and data.get("ok"):
                    data["inputs_path"] = str(inputs_out)
                    data["dim"] = spec.get("dim", default_dim)

                return data
            finally:
                try:
                    spec_file.unlink(missing_ok=True)
                except OSError:
                    pass

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
                "native_mode": {
                    "warpx_bin_dir": warpx_bin_dir or "(not configured)",
                    "ld_library_path_prepend": ld_library_path_prepend,
                    "tool": "build_warpx_native_submit_script",
                },
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
                "inputgen": {
                    "tool": "generate_warpx_inputs",
                    "warpx_inputgen_bin": (
                        _find_inputgen_bin(inputgen_bin_default, venv_activate_default)
                        or "(not found — install pywarpx in the WarpX science venv)"
                    ),
                    "sim_types": sorted(_SIM_TYPES),
                    "workflow": [
                        "1. generate_warpx_inputs(sim_type, spec, out_dir) → {ok, inputs_path, dim}",
                        "2. build_warpx_native_submit_script(run_dir=out_dir, inputs_file=inputs_path, dim=dim, ...)",
                        "3. submit_pbs_job(workspace_id=..., queue=..., walltime=..., select_spec=..., filesystems=..., account=...)",
                    ],
                },
                "examples": {
                    "electrostatic_plasma": (
                        "generate_warpx_inputs("
                        "sim_type='electrostatic_plasma', "
                        "spec={'dim':1,'number_of_cells':[100],'lower_bound':[0.0],'upper_bound':[0.005],"
                        "'field_bc':['periodic'],'max_steps':200,'n0':1e16,'Te':1.0,"
                        "'ion_mass_amu':1.0,'ppc':100,'diag_period':50}, "
                        "out_dir='/path/to/run')"
                    ),
                    "hybrid_plasma": (
                        "generate_warpx_inputs("
                        "sim_type='hybrid_plasma', "
                        "spec={'dim':1,'number_of_cells':[512],'lower_bound':[0.0],'upper_bound':[0.064],"
                        "'field_bc':['periodic'],'max_steps':1000,'Te':0.05,'substeps':40,"
                        "'n0_ref':3.3e22,'ion_density':3.3e22,'ion_mass_amu':1.0,'ion_temperature_eV':0.05,"
                        "'ppc':64,'B0':[0,0,0.25],'const_dt':1.3e-9,'diag_period':100}, "
                        "out_dir='/path/to/run')"
                    ),
                    "ion_beam_instability": (
                        "generate_warpx_inputs("
                        "sim_type='ion_beam_instability', "
                        "spec={'dim':1,'number_of_cells':[1024],'lower_bound':[0.0],'upper_bound':[0.256],"
                        "'field_bc':['periodic'],'max_steps':2000,'Te':0.05,'substeps':40,"
                        "'n0_ref':3.3e22,'core_density':2.97e22,'core_mass_amu':1.0,'core_temperature_eV':0.05,'core_ppc':256,"
                        "'beam_density':3.3e21,'beam_mass_amu':1.0,'beam_temperature_eV':0.05,'beam_ppc':64,"
                        "'beam_drift_velocity':2.4e6,'core_drift_velocity':0.0,"
                        "'B0':[0,0,0.25],'const_dt':1.3e-10,'diag_period':100}, "
                        "out_dir='/path/to/run')"
                    ),
                    "laser_acceleration": (
                        "generate_warpx_inputs("
                        "sim_type='laser_acceleration', "
                        "spec={'dim':2,'number_of_cells':[128,512],'lower_bound':[-2e-5,0.0],'upper_bound':[2e-5,2e-4],"
                        "'field_bc':['periodic','open'],'max_steps':50,'cfl':0.99,"
                        "'plasma_density':1e24,'plasma_zmin':2e-5,'plasma_zmax':1.8e-4,"
                        "'wavelength':8e-7,'a0':2.0,'waist':1.5e-5,'duration':3e-14,"
                        "'focal_position_z':6e-5,'centroid_position_z':0.0,'diag_period':25}, "
                        "out_dir='/path/to/run')"
                    ),
                    "magnetic_reconnection": (
                        "generate_warpx_inputs("
                        "sim_type='magnetic_reconnection', "
                        "spec={'dim':2,'number_of_cells':[512,256],'lower_bound':[0.0,-0.025],'upper_bound':[0.050,0.025],"
                        "'field_bc':['periodic','periodic'],'max_steps':2000,'Te':0.05,'substeps':40,"
                        "'n0_ref':1e20,'ion_density':1e20,'ion_mass_amu':0.22,'ion_temperature_eV':0.25,'ppc':100,"
                        "'B0':0.1,'Bg':0.0,'delta':1.25e-3,'dB_fraction':0.01,'const_dt':1e-11,'diag_period':100}, "
                        "out_dir='/path/to/run')"
                    ),
                    "pwfa": (
                        "generate_warpx_inputs("
                        "sim_type='pwfa', "
                        "spec={'dim':2,'number_of_cells':[128,512],'lower_bound':[-1.5e-4,-2e-4],'upper_bound':[1.5e-4,0.0],"
                        "'field_bc':['open','open'],'max_steps':1000,'cfl':0.99,"
                        "'plasma_density':1e22,'plasma_zmin':-2e-4,'plasma_zmax':0.0,"
                        "'driver_x_rms':2e-6,'driver_y_rms':2e-6,'driver_z_rms':4e-6,"
                        "'driver_uz_m':2000.0,'driver_q_tot':-1e-9,'driver_z_mean':-5e-5,'driver_n_macro':1000,"
                        "'moving_window':True,'diag_period':50}, "
                        "out_dir='/path/to/run')"
                    ),
                    "uniform_plasma": (
                        "generate_warpx_inputs("
                        "sim_type='uniform_plasma', "
                        "spec={'dim':3,'number_of_cells':[32,32,32],'lower_bound':[0.0,0.0,0.0],'upper_bound':[0.01,0.01,0.01],"
                        "'field_bc':['periodic','periodic','periodic'],'max_steps':100,"
                        "'plasma_density':1e20,'B0':[0,0,0.1],'diag_period':25}, "
                        "out_dir='/path/to/run')"
                    ),
                    "electromagnetic_pic": (
                        "generate_warpx_inputs("
                        "sim_type='electromagnetic_pic', "
                        "spec={"
                        "'dim':2,'number_of_cells':[256,512],"
                        "'lower_bound':[-50e-6,0.0],'upper_bound':[50e-6,200e-6],"
                        "'field_bc':['periodic','pml'],'max_steps':500,'cfl':0.99,"
                        "'maxwell_solver':'yee','particle_pusher':'boris',"
                        "'species':["
                        "{'name':'electrons','charge':-1,'mass_amu':5.486e-4,'density':1e24,'ppc':4,'temperature_eV':1000.0,'zmin':20e-6,'zmax':180e-6},"
                        "{'name':'protons','charge':1,'mass_amu':1.007276,'density':1e24,'ppc':4,'zmin':20e-6,'zmax':180e-6}"
                        "],"
                        "'collisions':[{'name':'coul_ei','type':'coulomb','species':['electrons','protons'],'CoulombLog':10.0}],"
                        "'diag_period':50,'diag_fields':['Ex','Ey','Ez','Bx','By','Bz','rho']}, "
                        "out_dir='/path/to/run')"
                    ),
                    "electromagnetic_pic_nuclear_fusion": (
                        "generate_warpx_inputs("
                        "sim_type='electromagnetic_pic', "
                        "spec={"
                        "'dim':1,'number_of_cells':[512],"
                        "'lower_bound':[0.0],'upper_bound':[0.001],"
                        "'field_bc':['periodic'],'max_steps':2000,'cfl':0.99,"
                        "'species':["
                        "{'name':'deuterium','charge':1,'mass_amu':2.014,'density':1e26,'ppc':4},"
                        "{'name':'tritium','charge':1,'mass_amu':3.016,'density':1e26,'ppc':4},"
                        "{'name':'helium4','charge':2,'mass_amu':4.003,'injection_style':'none'},"
                        "{'name':'neutron','charge':0,'mass_amu':1.009,'injection_style':'none'}"
                        "],"
                        "'collisions':[{'name':'dt_fusion','type':'nuclearfusion',"
                        "'species':['deuterium','tritium'],"
                        "'product_species':['helium4','neutron'],'event_multiplier':1e13}],"
                        "'diag_period':100,'diag_fields':['Ex','Bz','rho']}, "
                        "out_dir='/path/to/run')"
                    ),
                    "electrostatic_pic": (
                        "generate_warpx_inputs("
                        "sim_type='electrostatic_pic', "
                        "spec={"
                        "'dim':1,'number_of_cells':[400],"
                        "'lower_bound':[0.0],'upper_bound':[0.01],"
                        "'field_bc':['periodic'],'max_steps':500,'const_dt':5e-12,"
                        "'poisson_solver':'multigrid',"
                        "'species':["
                        "{'name':'electrons','charge':-1,'mass_amu':5.486e-4,'density':1e18,'ppc':16,'temperature_eV':10.0},"
                        "{'name':'nitrogen','charge':7,'mass_amu':14.003,'density':1e18,'ppc':4,"
                        "'do_field_ionization':True,'physical_element':'N',"
                        "'ionization_initial_level':0,'ionization_product_species':'electrons'}"
                        "],"
                        "'diag_period':50,'diag_fields':['Ex','rho']}, "
                        "out_dir='/path/to/run')"
                    ),
                    "picmi": (
                        "build_warpx_submit_script("
                        "run_dir='/lus/flare/projects/<proj>/runs/case1', "
                        "driver_script='/path/to/inputs_case.py', "
                        "driver_args='--dim 3 --test', "
                        "num_nodes=1, account='<proj>')"
                    ),
                    "native": (
                        "build_warpx_native_submit_script("
                        "run_dir='/lus/flare/projects/<proj>/runs/hybrid1', "
                        "inputs_file='/path/to/inputs', "
                        "dim=1, num_nodes=1, account='<proj>')"
                    ),
                },
            }
