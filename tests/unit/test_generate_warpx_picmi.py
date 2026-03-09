"""End-to-end subprocess tests for generate_warpx_picmi.

These tests replicate the exact subprocess pathway used by the
generate_warpx_picmi MCP tool, verifying that:
  - warpx-inputgen is findable on PATH (skip if not installed)
  - Each PICMI gen-<sim_type> subcommand runs without error
  - The output .py file contains the expected PICMI boilerplate
  - The output file is valid Python (compiles without syntax errors)

We do NOT import the full WarpX MCP application (avoids fastmcp /
yaml deps in the test environment). Instead we replicate the
subprocess call that generate_warpx_picmi() makes.
"""
from __future__ import annotations

import json
import py_compile
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_inputgen() -> str | None:
    """Return path to warpx-inputgen on PATH, or None."""
    return shutil.which("warpx-inputgen")


def _run_picmi(inputgen_bin: str, sim_type: str, spec: dict, out_file: Path) -> dict:
    """Invoke warpx-inputgen gen-<sim_type> exactly as generate_warpx_picmi does."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(spec, f, indent=2)
        spec_path = f.name
    try:
        cmd_map = {
            "electromagnetic_pic":   "gen-electromagnetic-pic",
            "electrostatic_pic":     "gen-electrostatic-pic",
            "hybrid_plasma":         "gen-hybrid-plasma",
            "electrostatic_plasma":  "gen-electrostatic-plasma",
            "pwfa":                  "gen-pwfa",
            "magnetic_reconnection": "gen-magnetic-reconnection",
            "ion_beam_instability":  "gen-ion-beam-instability",
            "laser_acceleration":    "gen-laser-acceleration",
        }
        cmd = [inputgen_bin, cmd_map[sim_type], spec_path, "--out", str(out_file)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        try:
            return json.loads(result.stdout)
        except Exception:
            return {"ok": result.returncode == 0, "raw_stdout": result.stdout,
                    "stderr": result.stderr}
    finally:
        Path(spec_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def inputgen_bin():
    """Provide the warpx-inputgen binary path, skip if not found."""
    path = _find_inputgen()
    if path is None:
        pytest.skip("warpx-inputgen not found on PATH — install pywarpx to run these tests")
    return path


# ---------------------------------------------------------------------------
# Per-sim-type PICMI smoke tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sim_type,expected_solver,expected_content", [
    ("hybrid_plasma",         "HybridPICSolver",         ["sim.add_diagnostic", "sim.initialize_inputs"]),
    ("electromagnetic_pic",   "ElectromagneticSolver",   ["sim.add_diagnostic", "sim.initialize_inputs"]),
    ("electrostatic_pic",     "ElectrostaticSolver",     ["sim.add_diagnostic", "sim.initialize_inputs"]),
    ("electrostatic_plasma",  "ElectrostaticSolver",     ["sim.add_diagnostic", "sim.initialize_inputs"]),
    ("pwfa",                  "ElectromagneticSolver",   ["GaussianBunchDistribution", "sim.initialize_inputs"]),
    ("magnetic_reconnection", "HybridPICSolver",         ["sim.add_diagnostic", "sim.initialize_inputs"]),
    ("ion_beam_instability",  "HybridPICSolver",         ["sim.add_diagnostic", "sim.initialize_inputs"]),
    ("laser_acceleration",    "ElectromagneticSolver",   ["GaussianLaser", "sim.initialize_inputs"]),
])
def test_picmi_subprocess_ok(tmp_path, inputgen_bin, sim_type, expected_solver, expected_content):
    """generate_warpx_picmi subprocess path: default spec produces a valid PICMI script."""
    out_file = tmp_path / "driver.py"
    data = _run_picmi(inputgen_bin, sim_type, {}, out_file)

    assert data.get("ok"), f"warpx-inputgen failed for {sim_type}: {data}"
    assert out_file.exists(), f"Output file not created for {sim_type}"

    content = out_file.read_text()
    assert "from pywarpx import picmi" in content, f"Missing picmi import in {sim_type}"
    assert expected_solver in content, f"Expected solver {expected_solver!r} not in {sim_type} output"
    for fragment in expected_content:
        assert fragment in content, f"Expected {fragment!r} not in {sim_type} output"


@pytest.mark.parametrize("sim_type", [
    "hybrid_plasma",
    "electromagnetic_pic",
    "electrostatic_pic",
    "electrostatic_plasma",
    "pwfa",
    "magnetic_reconnection",
    "ion_beam_instability",
    "laser_acceleration",
])
def test_picmi_output_valid_python(tmp_path, inputgen_bin, sim_type):
    """Generated PICMI script is syntactically valid Python."""
    out_file = tmp_path / "driver.py"
    data = _run_picmi(inputgen_bin, sim_type, {}, out_file)
    if not data.get("ok"):
        pytest.skip(f"warpx-inputgen failed for {sim_type} — skipping syntax check")
    py_compile.compile(str(out_file), doraise=True)


def test_picmi_bad_spec_returns_error(tmp_path, inputgen_bin):
    """Invalid spec (bad dim) → returncode != 0 and ok=False in JSON output."""
    out_file = tmp_path / "driver.py"
    data = _run_picmi(inputgen_bin, "hybrid_plasma", {"dim": 99}, out_file)
    assert not data.get("ok"), f"Expected failure for bad spec, got: {data}"


def test_picmi_with_diag_format(tmp_path, inputgen_bin):
    """diag_format key flows through to the generated PICMI script."""
    spec = {"diag_format": "plotfile"}
    out_file = tmp_path / "driver.py"
    data = _run_picmi(inputgen_bin, "hybrid_plasma", spec, out_file)
    assert data.get("ok"), data
    content = out_file.read_text()
    assert "plotfile" in content


def test_picmi_em_pic_with_species(tmp_path, inputgen_bin):
    """electromagnetic_pic PICMI: named species appear in the generated script."""
    spec = {
        "dim": 1,
        "number_of_cells": [64],
        "lower_bound": [0.0],
        "upper_bound": [0.001],
        "field_bc": ["periodic"],
        "species": [
            {"name": "electrons", "charge": -1, "mass_amu": 5.486e-4, "density": 1e24, "ppc": 4},
            {"name": "protons",   "charge":  1, "mass_amu": 1.00728,  "density": 1e24, "ppc": 4},
        ],
    }
    out_file = tmp_path / "em_driver.py"
    data = _run_picmi(inputgen_bin, "electromagnetic_pic", spec, out_file)
    assert data.get("ok"), data
    content = out_file.read_text()
    assert "electrons" in content
    assert "protons" in content
