# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["cadquery-ocp-novtk==8.0.1.1.0", "pyyaml>=6.0"]
# ///
"""Write one box part as STEP with pose.write_part_step.

Usage: uv run --script step_header_probe.py OUT.step
The FILE_NAME time is fixed, whatever the environment holds.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("cad_motion_pose", Path(__file__).resolve().parents[2] / "scripts" / "pose.py")
assert _spec is not None and _spec.loader is not None
pose = importlib.util.module_from_spec(_spec)
sys.modules["cad_motion_pose"] = pose
_spec.loader.exec_module(pose)


def main() -> int:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    pose.write_part_step(Path(sys.argv[1]), pose.Part("TST-0001", "TST-0001 Box", BRepPrimAPI_MakeBox(10, 20, 30).Shape()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
