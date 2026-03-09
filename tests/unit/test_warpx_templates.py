from __future__ import annotations

# Import templates by path (not via package) so tests do not import application
# packages that depend on optional runtime deps (e.g., fastmcp) or optional
# config deps (e.g., pyyaml).
import importlib.util
from pathlib import Path


class _StubSystemConfig:
    def __init__(self) -> None:
        self.display_name = "Aurora"
        self.default_filesystems = ["home", "flare"]


_TEMPLATES_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "borealis_mcp"
    / "applications"
    / "warpx"
    / "templates.py"
)

spec = importlib.util.spec_from_file_location("warpx_templates", _TEMPLATES_PATH)
assert spec and spec.loader
warpx_templates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(warpx_templates)
WarpXTemplates = warpx_templates.WarpXTemplates


def _aurora_like_system() -> _StubSystemConfig:
    return _StubSystemConfig()


def test_warpx_template_includes_run_dir_and_mpiexec() -> None:
    syscfg = _aurora_like_system()

    script = WarpXTemplates.generate_submit_script(
        system_config=syscfg,
        job_name="warpx",
        account="proj",
        queue="debug",
        walltime="00:30:00",
        filesystems="home:flare",
        run_dir="/lus/flare/projects/p/run1",
        modules=["adios2/x", "hdf5/y"],
        env_vars={"MPIR_CVAR_ENABLE_GPU": "1"},
        warpx_prefix=None,
        profile_source="$HOME/aurora_warpx.profile",
        venv_activate="/path/to/venv/bin/activate",
        mpi_command="mpiexec",
        mpi_env_flag="-genvall",
        mpi_flags=[],
        num_nodes=1,
        ranks_per_node=12,
        threads_per_rank=1,
        driver_basename="inputs.py",
        driver_args="--dim 3 --test",
        cpu_bind="--cpu-bind=list:1-8",
        gpu_bind="--gpu-bind=list:0.0",
    )

    assert "RUN_DIR=\"/lus/flare/projects/p/run1\"" in script
    assert "cd \"${RUN_DIR}\"" in script
    assert "mpiexec --np $NTOTRANKS" in script
    assert "-ppn $NRANKS_PER_NODE" in script
    assert "./inputs.py --dim 3 --test" in script


def test_warpx_native_template() -> None:
    syscfg = _aurora_like_system()

    script = WarpXTemplates.generate_native_submit_script(
        system_config=syscfg,
        job_name="hybrid1",
        account="proj",
        queue="debug",
        walltime="00:30:00",
        filesystems="home:flare",
        run_dir="/lus/flare/projects/p/runs/hybrid1",
        modules=["adios2/x", "hdf5/y"],
        env_vars={"MPIR_CVAR_ENABLE_GPU": "1"},
        ld_library_path_prepend=[
            "/install/warpx/lib",
            "/install/openPMD/lib64",
        ],
        profile_source="$HOME/warpx.modules",
        warpx_bin_dir="/install/warpx/bin",
        dim=1,
        mpi_command="mpiexec",
        mpi_env_flag="-genvall",
        mpi_flags=[],
        num_nodes=1,
        ranks_per_node=12,
        threads_per_rank=1,
        inputs_basename="inputs",
        cli_overrides="max_step=0",
        cpu_bind="--cpu-bind=list:1-8",
        gpu_bind="--gpu-bind=list:0.0",
    )

    # PBS header
    assert "#PBS -A proj" in script
    assert "#PBS -N hybrid1" in script

    # Run directory
    assert "RUN_DIR=\"/lus/flare/projects/p/runs/hybrid1\"" in script

    # Binary glob for 1d
    assert 'ls "/install/warpx/bin/warpx.1d."*' in script
    assert "warpx.1d" in script

    # LD_LIBRARY_PATH prepend
    assert "/install/warpx/lib" in script
    assert "/install/openPMD/lib64" in script
    assert "LD_LIBRARY_PATH" in script

    # MPI invocation
    assert "mpiexec --np $NTOTRANKS" in script
    assert "-ppn $NRANKS_PER_NODE" in script
    assert "-genvall" in script

    # Inputs file and overrides
    assert "inputs max_step=0" in script

    # No Python / venv references (native binary doesn't use a Python driver)
    assert all("python" not in line.lower() for line in script.splitlines())
    assert "venv" not in script
