# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["click==8.5.1", "cadquery-ocp-novtk==8.0.1.1.0", "jsonschema>=4.23", "pyyaml>=6.0", "trimesh==4.*", "numpy==2.5.5", "python-fcl==0.7.0.11"]
# ///
"""Test fixture: run `cad_model.py` with the mesher's control of every surface switched off, in this process only.

The agreement meshes its reference with the control on, and no solid overshoots the self-check's threshold then.
This driver wraps BRepMesh's parameter class so the control stays off, which reproduces the overshoot of an
uncontrolled torus fillet (0.0775 mm on lamp-arm's R44.85 mm, r1.2 mm fillet) and runs the production check on it, with
the default budget. Usage: uv run --script check_with_control_off.py <the arguments of cad_model.py>
"""

import runpy
import sys
from pathlib import Path

import OCP.IMeshTools as tools

CLI = Path(__file__).resolve().parents[2] / "scripts" / "cad_model.py"
CONTROL = "EnableControlSurfaceDeflectionAllSurfaces"
real = tools.IMeshTools_Parameters


class ControlOff(real):  # type: ignore[misc, valid-type]
    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, False if name == CONTROL else value)


tools.IMeshTools_Parameters = ControlOff
sys.path.insert(0, str(CLI.parent))  # a script run by its path finds its own folder. runpy does not
sys.argv = [str(CLI), *sys.argv[1:]]
runpy.run_path(str(CLI), run_name="__main__")
