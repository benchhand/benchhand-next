"""Shared helpers for corpus families: module loading, verdict mapping, cases for assembly operations.

Heavy imports (yaml, OCP, the check modules) happen inside the functions, so importing this is free.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from corpus import HERE, Outcome, Skip

SKILLS = HERE.parents[2]
REPO = SKILLS.parent
MOTION_FIXTURES = SKILLS / "cad-motion" / "tests" / "fixtures"
PNS = ("TST-0101", "TST-0102", "TST-0103", "TST-0104", "TST-0105")
TITLES = {"TST-0101": "Housing", "TST-0102": "Bearing", "TST-0103": "Cover", "TST-0104": "Cover screw",
          "TST-0105": "Bracket"}


def load(name: str, path: Path) -> Any:
    """One module per name, as scripts load their siblings under these names (scripts/modload.py)."""
    if str(REPO / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO / "scripts"))
    from modload import load_module

    return load_module(name, path)


def verdict(outcomes: Iterable[str]) -> Outcome:
    """A check's obligation outcomes as one verdict: any fail gives fail, else any unknown gives unknown, else pass."""
    seen = set(outcomes)
    if not seen:
        raise ValueError("a check that returns no outcome has no verdict")
    if "fail" in seen:
        return "fail"
    if "unknown" in seen:
        return "unknown"
    return "pass"


def require(module: str) -> None:
    """Raise Skip without the module."""
    import importlib.util

    if importlib.util.find_spec(module) is None:
        raise Skip(f"{module} is not installed")


# --- assembly operations (cad-record/scripts/assembly_operations.py) ---------------------------------------------

def operations_file(name: str, socket_sha256: str = "0" * 64) -> list[dict[str, Any]]:
    require("yaml")
    import yaml

    text = (MOTION_FIXTURES / name).read_text(encoding="utf-8").replace("{socket_sha256}", socket_sha256)
    data: list[dict[str, Any]] = yaml.safe_load(text)["operations"]
    return data


def reordered(items: list[dict[str, Any]], *ids: str) -> list[dict[str, Any]]:
    import copy

    by_id = {item["id"]: item for item in items}
    return [copy.deepcopy(by_id[ident]) for ident in ids]


def check_order(items: list[dict[str, Any]]) -> Mapping[str, str]:
    """{obligation: outcome} of assembly_operations.check_order over the access fixture's five parts."""
    require("yaml")
    ops = load("cad_record_assembly_operations", SKILLS / "cad-record" / "scripts" / "assembly_operations.py")
    data = load("cad_record_assembly_data", SKILLS / "cad-record" / "scripts" / "assembly_data.py")
    inventory = data.normalize({"subassemblies": [{"id": "main", "title": "Main", "parts": list(PNS)}]})
    report = ops.check_order(ops.normalize({"operations": items}), inventory)
    return {row["obligation"]: row["outcome"] for row in report.outcomes}


# --- additive (FDM) checks on real B-rep (cad-design process_checks) ---------------------------------------------

APPROVED = {"status": "approved", "rotation": {"quaternion": [1, 0, 0, 0]}, "decision": "DR-001"}
PN = "TST-0101"


def solids() -> Any:
    """access_fixture.py's OCP builders (box, cylinder, fuse, cut), reused rather than copied."""
    require("OCP")
    return load("mfg_corpus_access_fixture", MOTION_FIXTURES / "access_fixture.py")


def assess_printed(shape: Any, supports: Mapping[str, Any] | None = None, frame: str = "bed") -> Mapping[str, str]:
    """{obligation: outcome} of the fdm checks for one printed part: `shape` probed by form_check.probe with the
    plan the record asks for, then assessed against the TEST profile."""
    import tempfile
    from datetime import date

    require("OCP")
    require("yaml")
    require("jsonschema")
    import capability_profile

    for folder in (SKILLS / "cad-design" / "scripts", SKILLS / "cad-model" / "scripts"):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
    import process_checks as pc

    form_check = load("cad_design_form_check", SKILLS / "cad-design" / "scripts" / "form_check.py")
    fx = load("cad_record_mi_fixtures", SKILLS / "cad-record" / "tests" / "fixtures" / "manufacturing_intent.py")
    route = [fx.operation("print", "fdm", capability_profile.PRINTER, output_state="printed", orientation=dict(APPROVED),
                          supports=dict(supports or {"strategy": "none"}))]
    intent = fx.intent(functions=[{"function": "cosmetic"}], material_profile=capability_profile.MATERIAL, route=route,
                       critical_surfaces=fx.not_applicable("none here"))
    part = fx.part(PN, process="fdm", material=capability_profile.MATERIAL, part_intent=intent)
    documents = fx.record(parts=[part], capabilities=capability_profile.capabilities(),
                          materials=capability_profile.materials())
    with tempfile.TemporaryDirectory() as tmp:
        hw = fx.write_record(Path(tmp) / "project" / "hw", documents)
        record, problems = pc.intent().check_record(hw)
    errors = [f"{p.code} {p.path}: {p.message}" for p in problems if p.severity == "error"]
    if errors:
        raise ValueError(f"the corpus record is invalid: {errors}")
    today = date(2026, 6, 1)
    facts = form_check.probe(shape, frame=frame, locators={}, plan=pc.probe_plan(record, PN, "main", today=today))
    evidence = ({"path": f"hw/versions/v1/manufacturing/{PN}/part.step", "sha256": "0" * 64},)
    result = pc.assess(record, {(PN, "main"): pc.Geometry(PN, "main", facts, evidence)}, today=today)
    return {row["obligation"]: row["outcome"] for row in result.outcomes}


def printed_verdict(outcomes: Mapping[str, str], prefix: str) -> Outcome:
    """The verdict over the obligations whose id starts with `prefix`, e.g. "process.fdm.support@"."""
    return verdict(v for k, v in outcomes.items() if k.startswith(prefix))


# --- assembly access (cad-motion/scripts/access.py on the access fixture's geometry) -----------------------------

_ACCESS_ROOT: Path | None = None


def _access_geometry() -> tuple[Path, str]:
    """Build access_fixture.py's STEP parts once per process into a temp directory removed at exit."""
    import atexit
    import hashlib
    import shutil
    import subprocess
    import tempfile

    global _ACCESS_ROOT
    if _ACCESS_ROOT is None:
        if shutil.which("uv") is None:
            raise Skip("uv is required to build the access geometry")
        root = Path(tempfile.mkdtemp(prefix="mfg-corpus-access-"))
        atexit.register(shutil.rmtree, root, True)
        build = subprocess.run(["uv", "run", "--quiet", "--script", str(MOTION_FIXTURES / "access_fixture.py"),
                                str(root / "geometry")], capture_output=True, text=True, timeout=900, check=False)
        if build.returncode != 0:
            raise RuntimeError(f"access_fixture.py failed: {(build.stdout + build.stderr)[-1500:]}")
        _ACCESS_ROOT = root
    return _ACCESS_ROOT, hashlib.sha256((_ACCESS_ROOT / "geometry" / "socket.step").read_bytes()).hexdigest()


def socket_operations(name: str) -> list[dict[str, Any]]:
    """An operations file of cad-motion's fixtures with the built socket's sha256 bound."""
    require("yaml")
    return operations_file(name, _access_geometry()[1])


def access_outcomes(items: list[dict[str, Any]]) -> Mapping[str, str]:
    """{obligation: outcome} of access.py over the five parts with `items` as the assembly operations."""
    import json
    import shutil
    import subprocess
    import tempfile

    require("yaml")
    root, _ = _access_geometry()
    fx = load("cad_record_mi_fixtures", SKILLS / "cad-record" / "tests" / "fixtures" / "manufacturing_intent.py")
    parts = [fx.part(pn, TITLES[pn], process="cnc") for pn in PNS]
    interface = fx.interface("IF-001", "TST-0101", "TST-0102", "mounting",
                             limits={"press_fit": {"fit": "22 H7/p6", "pair": ["TST-0102", "TST-0101"]}})
    documents = fx.record(parts=parts, interfaces=[interface], operations=items)
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        hw = fx.write_record(Path(tmp) / "hw", documents)
        source = hw / "manufacturing" / "sources" / "socket.step"
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / "geometry" / "socket.step", source)
        attach = [arg for pn in PNS[1:] for arg in ("--attach", f"{pn}=TST-0101")]
        run = subprocess.run(["uv", "run", "--quiet", "--script", str(SKILLS / "cad-motion" / "scripts" / "access.py"),
                              "--hw", str(hw), "--parts-dir", str(root / "geometry" / "parts"), *attach],
                             capture_output=True, text=True, timeout=1800, check=False)
        if run.returncode not in (0, 1):
            raise RuntimeError(f"access.py exited {run.returncode}: {(run.stdout + run.stderr)[-1500:]}")
        result = json.loads(run.stdout)
    return {row["obligation"]: row["outcome"] for row in result["outcomes"]}
