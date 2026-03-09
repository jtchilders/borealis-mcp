# WarpX–Borealis Integration Contract

This document defines the interface between two cooperating subsystems:

- **`warpx-inputgen`** — input validation and generation CLI, living in the WarpX
  source tree at `Python/pywarpx/inputgen/`. Installed into the WarpX Python venv.
- **`borealis-mcp/applications/warpx`** — MCP application that generates PBS submit
  scripts, stages files, and tracks jobs. Lives in the borealis-mcp repo.

An LLM agent orchestrates the two:
1. Call `warpx-inputgen` to validate and generate inputs from a structured spec.
2. Call `build_warpx_submit_script` (or the future `build_warpx_native_submit_script`)
   to stage inputs and generate the PBS script.
3. Call `submit_pbs_job` to queue the job.

---

## 1. Run Modes

WarpX supports two distinct execution modes. Both are first-class; neither is a
workaround for the other.

### 1a. PICMI Mode

```
mpiexec ... python <script.py>
```

- The PICMI script calls `sim.initialize_warpx()` then `sim.step(N)`.
- Requires the `pywarpx` Python package with compiled pybind11 extensions
  (`warpx_pybind_2d.so`, etc.) discoverable at runtime.
- `WARPX_PYBIND_PATH` must point to the directory containing those `.so` files
  if they are not already on `pywarpx.__path__` (e.g. an editable source install
  paired with a CMake install prefix).
- Generated scripts include a preamble that reads `WARPX_PYBIND_PATH` and extends
  `pywarpx.__path__` accordingly.
- Field diagnostics should be disabled by default in generated scripts (plotfile
  writes from multiple ranks can fail if the output dir pre-exists).

**When to use:** Python-native workflows; callbacks; in-situ analysis; situations
where the PICMI API provides needed flexibility.

### 1b. Native Binary Mode

```
mpiexec ... warpx.2d inputs_file [key=value overrides ...]
```

- The WarpX C++ binary reads a native AMReX ParmParse inputs file directly.
- No Python bindings required at run time.
- Any ParmParse key can be overridden on the command line (e.g. `max_step=0`).
- Executables are named `warpx.1d`, `warpx.2d`, `warpx.3d`, `warpx.rz` (and
  with MPI/SYCL/DP suffixes on ALCF systems).

**When to use:** Production runs; systems where Python bindings are unavailable or
not trusted; maximum performance; smoke-test via `max_step=0`.

### Emit-Native Hybrid (internal detail)

`warpx-inputgen gen-laser-acceleration --emit-native-inputs <path>` patches the
generated PICMI script to call `sim.write_input_file()` instead of
`initialize_warpx()`. This runs on the login node (no GPU needed) and produces a
native inputs file. The resulting file is then used for a Native Binary run.
This is an implementation detail of `warpx-inputgen`; borealis-mcp sees only the
resulting native inputs file and treats the run as mode 1b.

---

## 2. warpx-inputgen CLI Reference

Installed as the `warpx-inputgen` console script.  All subcommands:
- Read a JSON spec file as their primary argument.
- Print a JSON object to **stdout** (`{"ok": true/false, ...}`).
- Exit `0` on success, `2` on validation error or bad inputs.

### 2.1 validate-laser-acceleration

```
warpx-inputgen validate-laser-acceleration <spec.json>
```

Validates a `LaserAccelerationSpec` JSON. Does not generate any files.

**stdout (success):**
```json
{"ok": true, "issues": []}
```
**stdout (validation error):**
```json
{
  "ok": false,
  "issues": [
    {"severity": "error", "code": "GRID_MISMATCH", "message": "...", "details": {...}}
  ]
}
```

### 2.2 gen-laser-acceleration

```
warpx-inputgen gen-laser-acceleration <spec.json> --out <script.py>
             [--dry-run | --emit-native-inputs <inputs_path>]
```

Generates a PICMI script for a laser acceleration run.

- **No flags**: writes a full PICMI script (PICMI mode, section 1a).
- **`--dry-run`**: patches the script to call only `initialize_inputs()` then
  print `DRYRUN_OK` and exit. Safe to run on login nodes.
- **`--emit-native-inputs <path>`**: patches the script to call
  `sim.write_input_file(file_name=<path>)` then print `WROTE_NATIVE_INPUTS` and
  exit. Produces native inputs without GPU. Safe on login nodes.

`--dry-run` and `--emit-native-inputs` are mutually exclusive.

**stdout (success):**
```json
{
  "ok": true,
  "out": "/path/to/script.py",
  "dry_run": false,
  "emit_native_inputs": null
}
```

### 2.3 validate-uniform-plasma / gen-uniform-plasma / gen-uniform-plasma-native

Same pattern as the laser acceleration family.  `gen-uniform-plasma-native`
writes a native AMReX ParmParse inputs file directly (no PICMI intermediate).

```
warpx-inputgen gen-uniform-plasma-native <spec.json> --out <inputs_file>
```

**stdout (success):**
```json
{"ok": true, "out": "/path/to/inputs_file"}
```

### 2.4 Spec JSON Formats

**LaserAccelerationSpec** (representative fields):
```json
{
  "name": "laser_acceleration",
  "dim": 2,
  "number_of_cells": [128, 512],
  "lower_bound": [-2.0e-05, 0.0],
  "upper_bound": [2.0e-05, 0.0002],
  "field_bc": ["periodic", "open"],
  "max_steps": 50,
  "cfl": 0.99,
  "plasma_density": 1.0e24,
  "plasma_zmin": 2.0e-05,
  "plasma_zmax": 1.8e-04,
  "wavelength": 8.0e-07,
  "a0": 2.0,
  "waist": 1.5e-05,
  "duration": 3.0e-14,
  "focal_position_z": 6.0e-05,
  "centroid_position_z": 0.0,
  "particle_shape": "linear",
  "diag_period": 50
}
```

**UniformPlasmaSpec** (representative fields):
```json
{
  "name": "uniform_plasma",
  "dim": 3,
  "number_of_cells": [64, 64, 64],
  "lower_bound": [0.0, 0.0, 0.0],
  "upper_bound": [1.0e-4, 1.0e-4, 1.0e-4],
  "field_bc": ["periodic", "periodic", "periodic"],
  "max_steps": 100,
  "cfl": 0.99,
  "density": 1.0e20,
  "temperature_eV": 1.0,
  "particle_shape": 1
}
```

---

## 3. Environment Contract

### Login-node environment (warpx-inputgen invocation)

| Variable | Purpose | Set by |
|---|---|---|
| `WARPX_PYBIND_PATH` | Dir containing `warpx_pybind_*.so`; extends `pywarpx.__path__` | Profile |
| `LD_LIBRARY_PATH` | Must include WarpX and openPMD lib dirs | Profile |
| Python venv | Must have `pywarpx` installed (editable OK) | Profile |

The profile script (`aurora_warpx_installShared.profile` or equivalent) must set
all of the above before invoking `warpx-inputgen`.

### Compute-node environment (PBS job)

| Variable | Purpose | Set by |
|---|---|---|
| `WARPX_PYBIND_PATH` | As above (PICMI mode only) | Profile |
| `LD_LIBRARY_PATH` | WarpX + openPMD lib dirs | Profile |
| `WARPX_BIN_DIR` | Dir containing `warpx.Xd` executables (native mode) | Profile or app config |
| `MPIR_CVAR_ENABLE_GPU` | Enable GPU in MPI (`"1"`) | App config env_vars |
| `ZE_FLAT_DEVICE_HIERARCHY` | Intel GPU topology (`"COMPOSITE"`) | App config env_vars |

`WARPX_BIN_DIR` is not currently set by the profile; it must be added or baked
into the app config `environment` block (see section 5).

### Executables

| Mode | Executable |
|---|---|
| PICMI | `python` (from activated venv) |
| Native 2D | `${WARPX_BIN_DIR}/warpx.2d.MPI.SYCL.DP.PDP.OPMD.EB.QED.GENQEDTABLES` |
| Native 3D | `${WARPX_BIN_DIR}/warpx.3d.MPI.SYCL.DP.PDP.OPMD.EB.QED.GENQEDTABLES` |

The full suffix (MPI.SYCL.DP…) is system-specific. On Aurora/Sunspot the installed
binary is discoverable via glob `warpx.2d.*` in `${WARPX_BIN_DIR}`.  The app
config or template should resolve the actual binary name at script generation time.

---

## 4. File Layout in run_dir

### PICMI mode

```
run_dir/
  script.py          # staged PICMI driver (generated by warpx-inputgen)
  submit.sh          # PBS script (generated by borealis-mcp)
  warpx_stdout.log   # PBS job stdout
  warpx_stderr.log   # PBS job stderr
  log.out            # mpiexec output
  diags/             # WarpX diagnostic output (openPMD/plotfile)
  warpx_used_inputs  # WarpX echoes final resolved inputs here
```

### Native binary mode

```
run_dir/
  inputs             # ParmParse inputs file (generated by warpx-inputgen or by hand)
  submit.sh          # PBS script (generated by borealis-mcp)
  warpx_stdout.log
  warpx_stderr.log
  log.out
  diags/
  warpx_used_inputs
```

---

## 5. borealis-mcp WarpX Tool Changes Needed

### 5.1 Current tool: `build_warpx_submit_script`

Covers PICMI mode only.  The PBS script runs:
```bash
mpiexec ... ./{driver_basename} {driver_args} > log.out
```

### 5.2 Required addition: native binary support

The existing tool should be extended (or a parallel tool added) to support native
binary runs.  The key differences:

| Aspect | PICMI (current) | Native binary (needed) |
|---|---|---|
| Staged file | `driver_script` (`.py`) | `inputs_file` (ParmParse) |
| Run command | `python script.py` | `warpx.2d inputs [overrides]` |
| Python venv | Required | Not required |
| `WARPX_PYBIND_PATH` | Required | Not required |
| `WARPX_BIN_DIR` | Not used | Required |

**Proposed new parameter: `run_mode`** (`"picmi"` | `"native"`)

For `run_mode="native"`, `driver_script` is replaced by `inputs_file`, and the
PBS template runs the binary directly.  Alternatively, a separate tool
`build_warpx_native_submit_script` can be added to keep the signatures clean.

**Proposed new app config key: `warpx_bin_dir`**

```yaml
# config/applications/warpx/aurora.yaml
warpx_bin_dir: "/flare/catalyst/world_shared/zippy/warpx/install/warpx/bin"
```

Or resolved via env var `WARPX_BIN_DIR` at job runtime.

**PBS template change for native mode:**

```bash
# --- Run (native binary) -----------------------------------------------------
INPUTS_FILE="{inputs_basename}"

echo "Starting WarpX (native) at $(date)"
echo "{mpi_command} ... {warpx_binary} $INPUTS_FILE {cli_overrides}"
{mpi_command} --np $NTOTRANKS -ppn $NRANKS_PER_NODE {bind_str} {mpi_env_flag} \
    {warpx_binary} $INPUTS_FILE {cli_overrides} > log.out
```

Where `{warpx_binary}` is the resolved absolute path to the `warpx.Xd` binary and
`{cli_overrides}` is an optional string of `key=value` ParmParse overrides
(e.g. `max_step=0` for a smoke test).

### 5.3 get_warpx_info update

Should report `warpx_bin_dir` and which run modes are configured.

---

## 6. Recommended Workflow (LLM Agent)

### PICMI run

1. `warpx-inputgen validate-laser-acceleration spec.json` → check `ok`
2. `warpx-inputgen gen-laser-acceleration spec.json --out run_dir/script.py`
3. `build_warpx_submit_script(run_dir=..., driver_script="run_dir/script.py", ...)`
4. `submit_pbs_job(workspace_id=..., account=..., ...)`

### Native binary run (direct)

1. `warpx-inputgen validate-laser-acceleration spec.json` → check `ok`
2. `warpx-inputgen gen-laser-acceleration spec.json --emit-native-inputs run_dir/inputs`
3. `python run_dir/script.py` (on login node) → prints `WROTE_NATIVE_INPUTS`
4. `build_warpx_native_submit_script(run_dir=..., inputs_file="run_dir/inputs", dim=2, ...)`
5. `submit_pbs_job(...)`

Or, once `gen-laser-acceleration-native` is implemented:

1. `warpx-inputgen validate-laser-acceleration spec.json` → check `ok`
2. `warpx-inputgen gen-laser-acceleration-native spec.json --out run_dir/inputs`
3. `build_warpx_native_submit_script(run_dir=..., inputs_file="run_dir/inputs", dim=2, ...)`
4. `submit_pbs_job(...)`

### Smoke test

After step 2 or 3 above (native inputs exist):
```
mpiexec -n 1 warpx.2d run_dir/inputs max_step=0
```
Can be run on a compute node via SSH before submitting the full job.

---

## 7. Open Items / Future Work

- `gen-laser-acceleration-native`: direct native ParmParse generation without the
  PICMI intermediate step. Avoids needing `sim.write_input_file()` on the login node.
- 3D support in `LaserAccelerationSpec` (currently hardcoded to `dim=2`).
- Boosted frame variant of laser acceleration.
- `ohm-solver` / hybrid-PIC family (distinct solver mode, high value).
- Composable building blocks (`DomainSpec`, `SolverSpec`, `SpeciesSpec`, etc.) to
  avoid monolithic spec growth as more physics families are added.
- `WARPX_BIN_DIR` in profile and app config (prereq for native mode in borealis-mcp).
