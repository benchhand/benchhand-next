# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""assembly.access: a fitted partner is exempt over its declared engagement length only.

A pin presses into a sleeve that sits in a housing. The pin and sleeve are a declared fit.
Only a press fit or heat-set may exempt interference, and only over its own engagement_length_mm, counted
from the installed pose along the insertion path. Each pair changes one defect a design agent could make.
The pin goes straight down unless the case declares a path. Engagement is the travel
over which the pin interferes with the sleeve, so with a pin installed at z 8 it equals the sleeve top minus 8.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from corpus import Family, Pair, Skip
from support import access_packet_verdict

REPO = Path(__file__).resolve().parents[5]
MOTION = REPO / "skills" / "cad-motion"
HOUSING, SLEEVE, PIN = "TST-0101", "TST-0102", "TST-0104"
SLEEVE_BASE_Z_MM = 8.0
PRESS_RADIUS_MM = 5.05  # 0.05 mm radial interference with the r 5 sleeve bore
SHANK_RADIUS_MM = 4.9  # 0.1 mm radial clearance in the r 5 sleeve bore


@dataclass(frozen=True)
class Case:
    sleeve_height_mm: float = 8.0
    bore_radius_mm: float = 5.0
    collar_height_mm: float = 0.0  # a pilot collar above the sleeve, bored like the sleeve
    rib: bool = False  # a lug standing on the sleeve top beside the bore
    groove: bool = False  # a 0.4 mm relief groove across the bore
    pin: str = "press"  # press (interference band), bead (0.2 mm press land) or clear (a shank with clearance)
    fit: str = "press_fit"  # the declaration on the pin and sleeve pair
    length_mm: float | None = 8.0  # engagement_length_mm, absent when None
    declared_path: bool = False  # the pin slides in sideways above the sleeve, then down


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _shapes(fixture, case: Case):
    cylinder, box, fuse, cut = fixture.cylinder, fixture.box, fixture.fuse, fixture.cut
    housing = cut(box(-30, -30, 0, 30, 30, 20), cylinder(0, 0, SLEEVE_BASE_Z_MM, 11, 13))
    top = SLEEVE_BASE_Z_MM + case.sleeve_height_mm
    outer = cylinder(0, 0, SLEEVE_BASE_Z_MM, 11, case.sleeve_height_mm)
    if case.collar_height_mm:
        outer = fuse(outer, cylinder(0, 0, top, 6.5, case.collar_height_mm))
    if case.rib:
        outer = fuse(outer, box(-11, -2, top, -7, 2, top + 3))
    sleeve = cut(outer, cylinder(0, 0, SLEEVE_BASE_Z_MM - 1, case.bore_radius_mm, case.sleeve_height_mm + case.collar_height_mm + 3))
    if case.groove:
        sleeve = cut(sleeve, cylinder(0, 0, 12.2, 6.0, 0.4))
    if case.pin == "press":
        pin = cylinder(0, 0, SLEEVE_BASE_Z_MM, PRESS_RADIUS_MM, 6)
    elif case.pin == "bead":
        pin = fuse(cylinder(0, 0, SLEEVE_BASE_Z_MM, SHANK_RADIUS_MM, 6), cylinder(0, 0, 9, PRESS_RADIUS_MM, 0.2))
    else:
        pin = cylinder(0, 0, SLEEVE_BASE_Z_MM, SHANK_RADIUS_MM, 6)
    return {HOUSING: housing, SLEEVE: sleeve, PIN: pin}


def _operations(case: Case) -> list[dict]:
    insert = {"id": "insert-pin", "kind": "join", "part": PIN, "into": HOUSING, "direction": [0, 0, -1],
              "acceptance": {"kind": "standoff", "features": ["pin_foot", "bore_floor"]}}
    if case.declared_path:
        insert["path"] = {"start": [-20, 0, 9.7], "via": [[0, 0, 9.7]]}
    return [{"id": "seat-sleeve", "kind": "press_fit", "part": SLEEVE, "into": HOUSING, "interface": "IF-001",
             "direction": [0, 0, -1], "acceptance": {"kind": "seated", "features": ["outer_face", "seat_floor"]}}, insert]


def verdict(case: Case) -> str:
    uv = shutil.which("uv")
    if uv is None:
        raise Skip("uv is not installed")
    fixture = _load("mfg_access_fixture", MOTION / "tests" / "fixtures" / "access_fixture.py")
    records = _load("mfg_record_fixtures", REPO / "skills" / "cad-record" / "tests" / "fixtures" / "manufacturing_intent.py")
    pose = fixture.pose
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        parts = root / "parts"
        parts.mkdir()
        for pn, shape in _shapes(fixture, case).items():
            pose.write_part_step(parts / f"{pn}.step", pose.Part(pn, pn, shape))
        declaration = {"fit": "10 H7/p6" if case.fit == "press_fit" else "10 H8/f7", "pair": [PIN, SLEEVE]}
        if case.length_mm is not None:
            declaration["engagement_length_mm"] = case.length_mm
        seat = records.interface("IF-001", HOUSING, SLEEVE, "mounting",
                                 limits={"press_fit": {"fit": "22 H7/p6", "pair": [SLEEVE, HOUSING]}})
        dowel = records.interface("IF-002", SLEEVE, PIN, "mounting", limits={case.fit: declaration})
        documents = records.record(parts=[records.part(pn, pn, process="cnc") for pn in (HOUSING, SLEEVE, PIN)],
                                   interfaces=[seat, dowel], operations=_operations(case))
        hw = records.write_record(root / "hw", documents)
        return access_packet_verdict(hw, parts, [f"{SLEEVE}={HOUSING}", f"{PIN}={HOUSING}"], "assembly.access@op:insert-pin")


TWIN = Case()


def _pair(pair_id: str, defect: str, mutant: Case, twin: Case = TWIN) -> Pair:
    return Pair(pair_id, defect, lambda is_mutant: verdict(mutant if is_mutant else twin))


FAMILY = Family(
    id="fitted_partner_exemption", check="skills/cad-motion/scripts/access.py", owner="pkgE",
    pairs=(
        _pair("rib_on_earlier_leg", "a lug on the sleeve blocks the pin's sideways leg before the bore",
              Case(rib=True, declared_path=True), Case(declared_path=True)),
        _pair("relief_groove_gap", "a groove breaks the pin's contact for less than one sample, then contact resumes",
              Case(pin="bead", groove=True, length_mm=7.0), Case(pin="bead", length_mm=7.0)),
        _pair("boss_thicker_than_declared", "the pin presses through a boss twice as thick as the declared engagement",
              Case(sleeve_height_mm=12.0)),
        _pair("length_short_by_one_step", "the declared engagement is 0.1 mm shorter than the real press",
              Case(length_mm=7.9)),
        _pair("length_not_declared", "the press fit has no engagement length", Case(length_mm=None)),
        _pair("over_long_pilot_collar", "a 3 mm pilot collar adds interference beyond the declared engagement",
              Case(collar_height_mm=3.0, length_mm=8.5), Case(collar_height_mm=0.5, length_mm=8.5)),
        _pair("bushing_bore_too_small", "a running-fit bushing bore is 0.05 mm smaller than the pin",
              Case(fit="running_fit", pin="clear", bore_radius_mm=4.85, length_mm=None),
              Case(fit="running_fit", pin="clear", length_mm=None)),
    ))
