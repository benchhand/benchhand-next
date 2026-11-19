#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""release.py: a frozen record releases one complete package; any gap refuses and writes nothing in hw/."""

from __future__ import annotations

import contextlib
import csv
import fcntl
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import tomllib
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from decision_fixture import decision_path, write_test_decision  # noqa: E402

SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / "scripts"
RELEASE = SCRIPTS / "release.py"
BUILD_GUIDE = SCRIPTS / "build_guide.py"
STACKUP = SKILL.parent / "cad-fits" / "scripts" / "stackup.py"
LAMP = SKILL.parent.parent / "examples" / "lamp-arm" / "hw"


def load(name: str, path: Path) -> Any:
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sys.modules[name])
    return sys.modules[name]


layout = load("cad_record_layout", SCRIPTS / "layout.py")
validate = load("cad_record_validate", SCRIPTS / "validate.py")
release = load("cad_record_release", RELEASE)
prune = load("cad_record_prune", SCRIPTS / "prune.py")
scriptenv = load("cadmodel_scriptenv", SKILL.parent / "cad-model" / "scripts" / "cadmodel" / "scriptenv.py")
acceptance = load("cad_record_acceptance_fixtures", SKILL / "tests" / "fixtures" / "acceptance.py")
fx, impact = acceptance.fx, acceptance.impact


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, text: str = "x\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def tree(root: Path) -> dict[str, str]:
    """Every file and directory below `root`: a file by its sha256, a directory as `dir`."""
    return {p.relative_to(root).as_posix(): ("dir" if p.is_dir() else sha(p)) for p in sorted(root.rglob("*"))}


def edit_yaml(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def edit_csv(path: Path, change: Callable[[list[dict[str, str]]], None]) -> None:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        columns, rows = reader.fieldnames, list(reader)
    change(rows)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(out.getvalue(), encoding="utf-8")


def publish(hw: Path, kind: str, subject: str, files: dict[str, str], status: str = "pass", version: str = "v1",
            recipe: dict[str, Any] | None = None) -> Path:
    staged = layout.staging(hw, f"bundle.{kind}")
    for name, text in files.items():
        write(staged / name, text)
    return layout.publish(hw, f"bundle.{kind}", {"V": version, "S": subject}, staged,
                          recipe=recipe or {"subject": subject}, producer="test", status=status).path


DRAWING = {"sheet-1.svg": "svg\n", "sheet-1.pdf": "pdf\n", "sheet-1.png": "png\n", "coverage.json": "{}\n",
           "package.json": "{}\n"}


def build_version(hw: Path, omit: tuple[tuple[str, str], ...] = (), failed: dict[str, str] | None = None,
                  attach: tuple[str, ...] = (), label: str = "v1") -> None:
    """hw/versions/<label> as cad-model run seals it: the record snapshot the layout's version.record set
    names, installed STEP per modelled part and the manufacturing outputs of every custom-made part. `omit`
    leaves (PN, file) out; `failed` marks a part's named manufacturing check failed; `attach` lists its
    `--attach REF=PARENT_REF` options."""
    folder = hw / "versions" / label
    pns = [p.parent.name for p in sorted((hw / "parts").glob("*/part.yaml"))]
    for name in layout.snapshot_names(hw, pns):
        target = folder / "record" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((hw / name).read_bytes())
    for name, data in fx.intent_module()._sibling("cad_record_guidelines", "guidelines.py").snapshot_files(hw).items():
        target = folder / "record" / name  # the winning shipped guideline sets, as cadmodel.record.snapshot copies them
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for name in ("assembly.step", "assembly.glb", "part-map.json", "metrics.json"):        write(folder / name, f"{name}\n")
    parts, made = {}, {}
    for model in sorted((hw / "parts").glob("*/model.py")):
        pn = model.parent.name
        write(folder / "parts" / f"{pn}.step", f"installed {pn}\n")
        parts[pn] = {"source_sha256": sha(model), "step": f"parts/{pn}.step"}
        record = yaml.safe_load((model.parent / "part.yaml").read_text(encoding="utf-8"))
        if not layout.custom_made(record):
            continue
        outputs = layout.manufacture_policy(record).outputs
        directory = folder / "manufacturing" / pn
        files = {name: sha(write(directory / name, f"{name} of {pn}\n"))
                 for name in outputs if name != "manufacturing.json" and (pn, name) not in omit}
        check = (failed or {}).get(pn)
        row = {"status": "fail" if check else "pass", "complete": not check, "blocking_failures": [check] if check else [],
               "checks": {"step": {"status": "pass"}, check or "placement": {"status": "fail" if check else "pass"}}}
        sidecar = {"schema_version": 1, "PN": pn, "process": record["process"], "outputs": list(outputs),
                   "path": f"manufacturing/{pn}", "files": files, **row}
        files["manufacturing.json"] = sha(write(directory / "manufacturing.json", json.dumps(sidecar, indent=2)))
        made[pn] = {"PN": pn, "process": record["process"], "path": f"manufacturing/{pn}", "files": files,
                    **{key: row[key] for key in ("status", "complete", "blocking_failures")}}
    inventory = {p.relative_to(folder).as_posix(): sha(p) for p in sorted(folder.rglob("*")) if p.is_file()}
    manifest = {"schema_version": 3, "label": label, "product_id": "lamp-arm", "attach": list(attach), "parts": parts,
                "record": {k: v for k, v in inventory.items() if k.startswith("record/")}, "manufacturing": made,
                "files": inventory}
    write(folder / "manifest.json", json.dumps(manifest, indent=2))
    write(hw / "versions" / "latest.json", json.dumps({"label": label, "manifest": f"versions/{label}/manifest.json"}))


def frozen_lamp(hw: Path, *, before_build: Callable[[Path], None] | None = None, omit: tuple[tuple[str, str], ...] = (),
                failed: dict[str, str] | None = None, skip_bundles: tuple[str, ...] = (), attach: tuple[str, ...] = (),
                label: str = "v1", older: tuple[str, ...] = (), service_class: str = "appearance_concept",
                ledger: Callable[[Path, Any, list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
                anchor: bool = True) -> None:
    """The lamp example migrated to record version 2 and reconciled for release (released revisions, a
    confirmed `service_class` use case and explicit routes, every software check of `label` passed by a
    sealed producer packet, verification passed with accepted ledger evidence), built as `label`, frozen at
    it with its acceptance digest (unless not `anchor`), every required bundle published, and DR-005
    approving it. Each `older` version is built first, with a check and a render bundle of its own;
    `ledger` may rewrite the accepted entries before the freeze."""
    fx.migrated_copy(LAMP, hw)
    for part in sorted((hw / "parts").glob("*/part.yaml")):
        edit_yaml(part, lambda data: data.update(rev="A"))
    edit_csv(hw / "bom.csv", lambda rows: [row.update(rev="A") for row in rows])
    write(hw / "analysis" / "cases" / "arm-load" / "case.yaml", "id: arm-load\n")
    write(hw / "docs" / "inspection.md", "# Inspection record\n")
    if before_build:
        before_build(hw)
    acceptance.release_ready(hw, service_class)
    if not yaml.safe_load((hw / "manufacturing" / "selection.yaml").read_text(encoding="utf-8")).get("candidates"):
        acceptance.confirm_selection(hw)  # a freeze and a release need the confirmed material and process selection
    for old in older:
        build_version(hw, label=old)
        publish(hw, "checks", "static", {"result.json": f'{{"status": "pass", "label": "{old}"}}\n'}, version=old)
        publish(hw, "renders", "iso", {"iso.png": f"{old} render\n"}, version=old)
    build_version(hw, omit, failed, attach, label)
    record = impact.read_record(hw)
    acceptance.publish_packet(hw, label, acceptance.producer_packet(record))
    evidence = {"REQ-002": f"sweep hw/motion/{label}/elbow-sweep", "REQ-004": f"hw/analysis/{label}/arm-load/results.json"}
    edit_csv(hw / "verification.csv", lambda rows: [row.update(result="pass", evidence=evidence.get(
        row["requirement_id"], "hw/docs/inspection.md")) for row in rows])
    version_sha = sha(hw / "versions" / label / "manifest.json")
    entries = [acceptance.entry(record, f"EV-{number:03d}", {"product": True, "requirements": [req]}, "cad_valid",
                                requirement=req, version=label, manifest_sha256=version_sha,
                                geometry=impact.current_geometry(hw), artifacts=["hw/docs/inspection.md"], hw=hw)
               for number, req in enumerate(sorted(record.requirements), start=1)]
    acceptance.write_ledger(hw, ledger(hw, record, entries) if ledger else entries)
    frozen = {"version": label, "manifest_sha256": version_sha, "decision": "DR-004"}
    if anchor:
        frozen["evidence_sha256"] = acceptance.freeze_anchor(hw, label)
    edit_yaml(hw / "product.yaml", lambda data: data["flow"].update(stage="release", frozen=frozen))
    write_test_decision(hw, "DR-005", context=f"Approved: release {label} as revision A.")
    for part in sorted((hw / "versions" / label / "record" / "parts").glob("*/part.yaml")):
        pn = part.parent.name
        if "drawing" in yaml.safe_load(part.read_text(encoding="utf-8")) and pn not in skip_bundles:
            publish(hw, "drawings", pn, DRAWING, version=label)
    publish(hw, "drawings", "assembly", DRAWING, version=label)
    publish(hw, "analysis", "arm-load", {"results.json": '{"status": "pass"}\n'}, version=label)
    publish(hw, "motion", "elbow-sweep", {"result.json": '{"status": "pass"}\n', "worst.step": "worst\n"}, version=label)


class ReleaseCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-release-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.count = 0

    @classmethod
    def default_project(cls) -> Path:
        """The project directory of frozen_lamp() with its default options, built once per test class.
        The fixture holds no absolute path or link, so each test copies it instead of building it again."""
        if "_default_project" not in cls.__dict__:
            temporary = tempfile.TemporaryDirectory(prefix="cad-release-fixture-")
            cls.addClassCleanup(temporary.cleanup)
            project = Path(temporary.name) / "project"
            frozen_lamp(project / "hw")
            cls._default_project = project
        return cls.__dict__["_default_project"]

    def project(self, **options: Any) -> Path:
        self.count += 1
        hw = self.root / f"project-{self.count}" / "hw"
        if options:
            frozen_lamp(hw, **options)
        else:
            shutil.copytree(self.default_project(), hw.parent, symlinks=True)
        return hw

    def release(self, hw: Path, rev: str = "A", version: str = "v1", decision: str = "DR-005",
                now: datetime | None = None) -> tuple[int, dict[str, Any]]:
        return release.run(hw, rev, version, decision, now)


class Release(ReleaseCase):
    def test_the_fixture_is_a_clean_frozen_record(self) -> None:
        hw = self.project()
        self.assertEqual(validate.blocking(validate.validate_project(hw)), [])

    def test_a_shipped_guideline_copy_in_the_snapshot_is_not_a_removed_file(self) -> None:
        from types import SimpleNamespace  # noqa: PLC0415 - used by this test only

        hw = self.project()
        record = hw / "versions" / "v1" / "record"
        manifest = json.loads((hw / "versions" / "v1" / "manifest.json").read_text(encoding="utf-8"))
        copy = record / "manufacturing" / "guidelines" / "shipped--pa.yaml"
        write(copy, "schema_version: 1\n")
        manifest["files"]["record/manufacturing/guidelines/shipped--pa.yaml"] = release.sha256(copy)
        refused: list[tuple[str, str, str]] = []
        fake = SimpleNamespace(hw=hw, version="v1", checks={}, refuse=lambda path, kind, message: refused.append((path, kind, message)))
        release.check_record(fake, record, manifest)
        self.assertEqual(refused, [])
        write(record / "manufacturing" / "other.yaml", "a: 1\n")
        manifest["files"]["record/manufacturing/other.yaml"] = release.sha256(record / "manufacturing" / "other.yaml")
        release.check_record(fake, record, manifest)
        self.assertEqual([r[0] for r in refused], ["hw/manufacturing/other.yaml"], "any other removed file still refuses")

    def test_a_project_file_named_like_a_shipped_copy_refuses_the_release(self) -> None:
        from types import SimpleNamespace  # noqa: PLC0415 - used by this test only

        hw = self.project()
        record = hw / "versions" / "v1" / "record"
        manifest = json.loads((hw / "versions" / "v1" / "manifest.json").read_text(encoding="utf-8"))
        name = "manufacturing/guidelines/shipped--escape.yaml"
        for root in (hw, record):
            write(root / name, "schema_version: 1\n")
        manifest["files"][f"record/{name}"] = release.sha256(record / name)
        refused: list[tuple[str, str, str]] = []
        fake = SimpleNamespace(hw=hw, version="v1", checks={}, refuse=lambda path, kind, message: refused.append((path, kind, message)))
        release.check_record(fake, record, manifest)
        self.assertEqual([(r[0], r[1]) for r in refused], [(f"hw/{name}", "reserved")])

    def test_an_edited_shipped_guideline_copy_in_the_snapshot_refuses(self) -> None:
        from types import SimpleNamespace  # noqa: PLC0415 - used by this test only

        hw = self.project()
        record = hw / "versions" / "v1" / "record"
        manifest = json.loads((hw / "versions" / "v1" / "manifest.json").read_text(encoding="utf-8"))
        copy = record / "manufacturing" / "guidelines" / "shipped--pa.yaml"
        write(copy, "schema_version: 1\n")
        manifest["files"]["record/manufacturing/guidelines/shipped--pa.yaml"] = release.sha256(copy)
        write(copy, "schema_version: 1\nedited: true\n")
        refused: list[tuple[str, str, str]] = []
        fake = SimpleNamespace(hw=hw, version="v1", checks={}, refuse=lambda path, kind, message: refused.append((path, kind, message)))
        release.check_record(fake, record, manifest)
        self.assertEqual([(r[0], r[1]) for r in refused], [("hw/manufacturing/guidelines/shipped--pa.yaml", "tampered")])

    def test_a_complete_frozen_record_releases_a_verified_package(self) -> None:
        hw = self.project()
        result = subprocess.run([sys.executable, str(RELEASE), str(hw), "--rev", "A", "--version", "v1",
                                 "--decision", "DR-005"], capture_output=True, text=True, timeout=120, check=False)
        report = json.loads(result.stdout)
        self.assertEqual((result.returncode, report["status"]), (0, "released"), report.get("findings"))
        package = hw / "releases" / "A"
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        findings: list[dict[str, Any]] = []
        self.assertTrue(validate.validate_document(manifest, "release-manifest.schema.json", "manifest", findings), findings)
        self.assertEqual((manifest["schema_version"], manifest["record_version"], manifest["rev"], manifest["approval"],
                          manifest["frozen"]["version"]), (3, 2, "A", "DR-005", "v1"))
        self.assertEqual(manifest["frozen"]["manifest_sha256"], sha(hw / "versions" / "v1" / "manifest.json"))
        self.assertEqual(layout.verify(package), [])
        for name, item in manifest["files"].items():
            self.assertEqual(sha(layout.locate(hw, item["original"])), item["sha256"], name)
        self.assertEqual(report["manifest_sha256"], sha(package / "manifest.json"))
        self.assertEqual(manifest["manufacturing"]["LMP-0001"],
                         {"process": "fdm", "quantity": 1, "route": ["fdm"],
                          "files": ["manufacturing/LMP-0001/part.step", "manufacturing/LMP-0001/part.stl",
                                    "manufacturing/LMP-0001/part.3mf", "manufacturing/LMP-0001/manufacturing.json"]})
        self.assertEqual(manifest["files"]["manufacturing/LMP-0001/part.3mf"]["original"],
                         "hw/versions/v1/manufacturing/LMP-0001/part.3mf")
        accepted = manifest["acceptance"]
        self.assertEqual(accepted["evidence_sha256"], manifest["frozen"]["evidence_sha256"])
        self.assertEqual(accepted["scope"]["service_class"], "appearance_concept")
        self.assertFalse(accepted["scope"]["trial"])
        self.assertEqual((accepted["claims"]["REQ-001"], accepted["waivers"]), (["cad_valid"], []))
        self.assertIn("process.fdm.trial@LMP-0001/make", accepted["open_obligations"], "untested, unclaimed, open")
        for path, digest in accepted["inventory"].items():
            self.assertEqual(manifest["files"][f"acceptance/{path[3:]}"], {"sha256": digest, "original": path})
        self.assertIn("hw/manufacturing/evidence.yaml", accepted["inventory"])
        self.assertEqual(manifest["checks"]["acceptance"], "pass")
        self.assertEqual(manifest["manufacturing"]["LMP-0002"]["files"],
                         ["manufacturing/LMP-0002/part.step", "manufacturing/LMP-0002/manufacturing.json"])
        selected = {item["path"]: item["manifest_sha256"] for item in manifest["bundles"]}
        self.assertEqual(set(selected), {f"hw/drawings/v1/LMP-00{n:02d}" for n in range(1, 11)}
                         | {"hw/drawings/v1/assembly", "hw/analysis/v1/arm-load", "hw/motion/v1/elbow-sweep"})
        for path, manifest_sha in selected.items():
            self.assertEqual(sha(layout.locate(hw, path) / "manifest.json"), manifest_sha)
        for name in ("definition/assembly.step", "definition/record/assembly.yaml", "drawings/assembly/sheet-1.pdf",
                     "analysis/arm-load/results.json", "motion/elbow-sweep/worst.step", "bom.csv", "verification.csv",
                     "docs/inspection.md"):
            self.assertTrue((package / name).is_file(), name)
        self.assertEqual(manifest["checks"]["verification/REQ-002"], "pass")
        self.assertEqual(list((hw.parent / ".cad-work" / "release-A").iterdir()), [], "the stage became the package")
        self.assertEqual(validate.blocking(validate.validate_project(hw)), [], "the released record still validates")

    def test_a_catalogue_buy_is_exempt_and_a_made_to_drawing_part_is_included(self) -> None:
        hw = self.project()
        code, report = self.release(hw)
        self.assertEqual(code, 0, report.get("findings"))
        package = hw / "releases" / "A"
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(manifest["manufacturing"]), [f"LMP-000{n}" for n in range(1, 8)])
        self.assertEqual(manifest["manufacturing"]["LMP-0005"],
                         {"process": "cnc", "quantity": 1, "route": ["cnc"],
                          "files": ["manufacturing/LMP-0005/part.step", "manufacturing/LMP-0005/manufacturing.json"]})
        catalogue = ("LMP-0008", "LMP-0009", "LMP-0010", "LMP-0011")
        self.assertEqual([name for name in manifest["files"]
                          if name.startswith(tuple(f"manufacturing/{pn}/" for pn in catalogue))], [])
        self.assertTrue((package / "definition" / "record" / "parts" / "LMP-0008" / "part.yaml").is_file(),
                        "a catalogue buy carries its procurement definition")
        self.assertTrue((package / "drawings" / "LMP-0008" / "sheet-1.pdf").is_file(), "its vendor specification sheet")

    def test_a_repeated_part_gives_one_output_with_its_occurrence_count(self) -> None:
        def make_ring(hw: Path) -> None:
            def custom(data: dict[str, Any]) -> None:
                data.update(make_buy="make", process="cnc")
                del data["procurement"]
            edit_yaml(hw / "parts" / "LMP-0011" / "part.yaml", custom)
            edit_csv(hw / "bom.csv", lambda rows: [row.update(
                make_buy="make", process="cnc", **dict.fromkeys(validate.BOM_PROCUREMENT_COLUMNS[1:], ""))
                for row in rows if row["PN"] == "LMP-0011"])

        hw = self.project(before_build=make_ring)
        code, report = self.release(hw)
        self.assertEqual(code, 0, report.get("findings"))
        manifest = json.loads((hw / "releases" / "A" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manufacturing"]["LMP-0011"],
                         {"process": "cnc", "quantity": 3, "route": ["cnc"],
                          "files": ["manufacturing/LMP-0011/part.step", "manufacturing/LMP-0011/manufacturing.json"]})
        self.assertEqual(sorted(n for n in manifest["files"] if n.startswith("manufacturing/LMP-0011/")),
                         ["manufacturing/LMP-0011/manufacturing.json", "manufacturing/LMP-0011/part.step"])

    def test_a_version_built_with_attach_releases(self) -> None:
        def unjoin(hw: Path) -> None:  # members cad-model attaches at run time instead of by a joint
            edit_yaml(hw / "assembly.yaml", lambda data: data.update(
                joints=[joint for joint in data["joints"] if joint["id"] not in ("J-009", "J-012")]))

        hw = self.project(before_build=unjoin, attach=("LMP-0010=LMP-0004", "@ring-head=LMP-0007"))
        self.assertEqual(validate.blocking(validate.validate_project(hw)), [])
        code, report = self.release(hw)
        self.assertEqual(code, 0, report.get("findings"))
        manifest = json.loads((hw / "releases" / "A" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manufacturing"]["LMP-0007"]["quantity"], 1)

    def test_a_passing_stack_case_releases_with_its_case_bundle(self) -> None:
        """stackup.py publishes the stack at hw/analysis/cases/<case>/case.yaml as hw/analysis/<V>/<case>/, the
        bundle release.py requires for that case, whatever the stack's own (uppercase) id."""
        hw = self.project()
        source = {"kind": "user", "reference": "TST stack input", "origin": "TST fixture user"}
        stack = {"intent_version": 2, "id": "STK-001", "title": "Bearing end float", "units": "mm",
                 "subject": {"PN": "LMP-0002", "feature": "hub_bore"}, "dimension_state": "assembled", "consequence": "performance",
                 "relevant": ["assembly"], "requirement": {"min": 0.0, "max": 0.40, "method": "worst_case", "source": source},
                 "contributors": [{"id": "A", "category": "assembly", "nominal": 50.0, "tol": 0.05, "direction": 1, "source": source},
                                  {"id": "B", "category": "assembly", "nominal": 49.8, "tol": 0.05, "direction": -1, "source": source}]}
        case = write(hw / "analysis" / "cases" / "end-float" / "case.yaml", yaml.safe_dump(stack, sort_keys=False))
        code, report = self.release(hw)
        self.assertEqual(code, 1)
        self.assertIn("analysis case end-float has no result for v1", json.dumps(report["findings"]))
        run = subprocess.run([sys.executable, str(STACKUP), str(case), "--hw", str(hw), "--version", "v1"],
                             capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout[-3000:])
        self.assertEqual(json.loads(run.stdout)["bundle"], str(hw / "analysis" / "v1" / "end-float"))
        code, report = self.release(hw)
        self.assertEqual(code, 0, report.get("findings"))
        manifest = json.loads((hw / "releases" / "A" / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("hw/analysis/v1/end-float", {item["path"] for item in manifest["bundles"]})

    def test_a_released_original_may_go_but_its_package_copy_may_not(self) -> None:
        hw = self.project()
        write(hw / "docs" / "notes.md", "# Notes\n")
        self.assertEqual(self.release(hw)[0], 0)
        (hw / "docs" / "notes.md").unlink()
        self.assertEqual(validate.blocking(validate.validate_project(hw)), [], "release A holds its own copy")
        (hw / "releases" / "A" / "docs" / "notes.md").unlink()
        self.assertIn("releases/A/docs/notes.md", json.dumps(validate.blocking(validate.validate_project(hw))))


# what pruning after release A of v3 removes from Pruning.released(), in order: each version's bundle
# roots in layout bundle-kind order, then the version itself
SUPERSEDED = ["hw/checks/v1", "hw/renders/v1", "hw/versions/v1", "hw/checks/v2", "hw/renders/v2", "hw/versions/v2"]


class Pruning(ReleaseCase):
    """--prune after release A of v3: v1 and v2 are superseded, v4 was built after v3 but latest.json names v3."""

    def released(self, *, seal: bool = True) -> Path:
        hw = self.project(label="v3", older=("v1", "v2"))
        build_version(hw, label="v4")
        write(hw / "versions" / "latest.json", json.dumps({"label": "v3", "manifest": "versions/v3/manifest.json"}))
        if seal:
            code, report = self.release(hw, version="v3")
            self.assertEqual(code, 0, report.get("findings"))
        return hw

    def cli(self, hw: Path, *extra: str, decision: str = "DR-005") -> tuple[int, dict[str, Any]]:
        result = subprocess.run([sys.executable, str(RELEASE), str(hw), "--rev", "A", "--version", "v3",
                                 "--decision", decision, "--prune", *extra], capture_output=True, text=True,
                                timeout=300, check=False)
        return result.returncode, json.loads(result.stdout)

    def journal(self, hw: Path, digest: str) -> Path:
        return hw.parent / ".cad-work" / f"prune-A-{digest[:16]}" / "journal.json"

    def assertGone(self, hw: Path, paths: list[str], gone: bool = True) -> None:
        for rel in paths:
            self.assertEqual(os.path.lexists(layout.locate(hw, rel)), not gone, rel)

    def test_plan_then_yes_through_the_cli_removes_only_superseded_versions(self) -> None:
        hw = self.released(seal=False)
        code, report = self.cli(hw)  # seals A, then plans
        self.assertEqual((code, report["status"], report["pruning"]["status"]), (0, "released", "plan"), report)
        plan = report["pruning"]["plan"]
        self.assertEqual((plan["prune"], plan["remove"]), (["v1", "v2"], SUPERSEDED))
        self.assertEqual(plan["keep"]["v4"], ["not older than the released v3"], "a newer build stays without latest.json")
        self.assertIn("released as A", plan["keep"]["v3"])
        before = tree(hw)
        code, again = self.cli(hw)  # A is sealed: the documented rerun plans without sealing again
        self.assertEqual((code, again["already_sealed"], again["pruning"]["plan"]["digest"]), (0, True, plan["digest"]))
        self.assertEqual(tree(hw), before, "a plan changes nothing")
        code, report = self.cli(hw, "--yes", plan["digest"])
        self.assertEqual((code, report["status"], report["pruning"]["status"]), (0, "released", "pruned"), report)
        self.assertEqual(list(report)[-1], "status")
        self.assertEqual(report["pruning"]["removed"], SUPERSEDED)
        self.assertEqual(report["pruning"]["store_gc"]["status"], "pass")
        self.assertGone(hw, SUPERSEDED)
        self.assertEqual(layout.versions(hw), ["v3", "v4"])
        self.assertEqual(layout.verify(hw / "releases" / "A"), [])
        self.assertEqual(list((hw.parent / ".cad-work").glob("prune-*")), [])
        self.assertEqual(validate.blocking(validate.validate_project(hw)), [], "no surviving reference broke")

    def test_yes_refuses_a_digest_that_a_fresh_plan_no_longer_has(self) -> None:
        hw = self.released()
        digest = prune.plan(hw, "A", "v3")["digest"]
        write_test_decision(hw, "DR-006", context="Keep v2 as the baseline.")
        before = tree(hw)
        code, report = self.cli(hw, "--yes", digest)
        self.assertEqual((code, report["status"], report["pruning"]["status"]), (1, "prune_refused", "refused"))
        self.assertEqual(report["pruning"]["plan"]["prune"], ["v1"])
        self.assertEqual(report["pruning"]["plan"]["keep"]["v2"], ["named by DR-006"])
        self.assertEqual(tree(hw), before)
        result = subprocess.run([sys.executable, str(RELEASE), str(hw), "--rev", "A", "--version", "v3", "--decision",
                                 "DR-005", "--prune", "--yes", "latest"], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 2)
        self.assertIn("64-character digest", result.stderr)

    def test_prune_on_a_stale_package_refuses_and_deletes_nothing(self) -> None:
        hw = self.released()
        write(hw / "releases" / "A" / "bom.csv", "edited\n")
        before = tree(hw)
        code, report = self.cli(hw)
        self.assertEqual((code, report["status"], report["findings"][0]["code"]), (1, "refused", "release.stale"))
        self.assertIn("release.py without --prune repairs it", report["findings"][0]["message"])
        self.assertNotIn("pruning", report)
        self.assertEqual(tree(hw), before)

    def test_an_existing_package_of_another_approval_is_refused_not_pruned_against(self) -> None:
        hw = self.released()
        before = tree(hw)
        code, report = self.cli(hw, decision="DR-004")
        self.assertEqual((code, report["status"], report["findings"][0]["code"]), (1, "refused", "release.exists"))
        self.assertNotIn("pruning", report)
        self.assertEqual(tree(hw), before)

    def test_store_gc_is_asked_for_json_whatever_the_caller_environment_says(self) -> None:
        done = subprocess.CompletedProcess([], 0, stdout='{"schema": "tool-result/1", "status": "pass", "findings": [], "payload": {"objects": {}}}', stderr="")
        with mock.patch.dict(os.environ, {"CAD_OUTPUT": "compact"}), \
                mock.patch.object(prune.subprocess, "run", return_value=done) as run:
            self.assertEqual(prune.store_gc(Path("hw")), {"objects": {}})
        self.assertEqual(run.call_args.kwargs["env"]["CAD_OUTPUT"], "json")

    @unittest.skipUnless(shutil.which("uv"), "uv is required to build release.py's declared environment")
    def test_store_gc_runs_under_the_dependencies_release_py_declares(self) -> None:
        # --prune runs cad_model.py store gc in release.py's interpreter, so release.py's header must cover it
        hw = self.released()
        # independent of gc's layout rules: each manifest.json seals its folder, bar copies inside a release package
        found = [path.relative_to(hw).parts for path in hw.rglob("manifest.json")]
        seals = sum(1 for parts in found if parts[0] != "releases" or len(parts) == 3)
        result = subprocess.run(scriptenv.python_command(RELEASE, "-B", str(prune.CAD_MODEL), "store", "gc", str(hw)),
                                capture_output=True, text=True, timeout=600, check=False, env=prune.emit.json_env())
        self.assertEqual(result.returncode, 0, result.stderr)
        collected = prune.emit.unwrap(json.loads(result.stdout))
        self.assertEqual((collected["status"], collected["manifests"]), ("pass", seals))

    def test_gc_failure_is_prune_incomplete_and_a_rerun_finishes(self) -> None:
        hw = self.released()
        digest = prune.plan(hw, "A", "v3")["digest"]
        staging = hw / "versions" / ".v5.partial-1"  # a cad-model run in progress: store gc refuses
        staging.mkdir()
        code, report = self.cli(hw, "--yes", digest)
        self.assertEqual((code, report["status"], report["pruning"]["status"]), (1, "prune_incomplete", "incomplete"))
        self.assertIn("store gc failed", report["pruning"]["message"])
        self.assertEqual(report["pruning"]["removed"], SUPERSEDED)
        self.assertGone(hw, SUPERSEDED)
        self.assertEqual(json.loads(self.journal(hw, digest).read_text(encoding="utf-8"))["phase"], "gc")
        staging.rmdir()
        code, report = self.cli(hw)  # a plan request names the pending prune instead of planning another
        self.assertEqual((code, report["pruning"]["status"], report["pruning"]["digest"]), (1, "incomplete", digest))
        code, report = self.cli(hw, "--yes", digest)
        self.assertEqual((code, report["status"], report["pruning"]["status"]), (0, "released", "pruned"), report)
        self.assertFalse(self.journal(hw, digest).parent.exists())

    def interrupt_after(self, count: int, hw: Path, digest: str) -> dict[str, Any]:
        rename, moved = os.rename, []

        def interrupted(source: Any, target: Any) -> None:
            if len(moved) == count:
                raise OSError("interrupted")
            moved.append(layout.relative(hw.resolve(), Path(source)))
            rename(source, target)

        with mock.patch.object(prune.os, "rename", interrupted):
            result = prune.after_release(hw, "A", "v3", digest)
        self.assertEqual(moved, SUPERSEDED[:count])
        return result

    def test_an_interrupted_prune_moves_whole_folders_and_a_rerun_finishes(self) -> None:
        hw = self.released()
        digest = prune.plan(hw, "A", "v3")["digest"]
        result = self.interrupt_after(2, hw, digest)
        self.assertEqual((result["status"], result["digest"]), ("incomplete", digest))
        self.assertEqual(layout.verify(hw / "versions" / "v1"), [], "v1 is untouched, never half deleted")
        self.assertGone(hw, SUPERSEDED[:2])
        self.assertGone(hw, SUPERSEDED[2:], gone=False)
        result = prune.after_release(hw, "A", "v3", digest)
        self.assertEqual((result["status"], result["removed"]), ("pruned", SUPERSEDED))
        self.assertGone(hw, SUPERSEDED)
        self.assertFalse(self.journal(hw, digest).parent.exists())

    def test_an_interrupted_prune_moves_back_a_version_that_became_a_milestone(self) -> None:
        hw = self.released()
        digest = prune.plan(hw, "A", "v3")["digest"]
        self.interrupt_after(3, hw, digest)  # every v1 folder has left hw/
        self.assertGone(hw, SUPERSEDED[:3])
        write_test_decision(hw, "DR-006", context="The PARTS gate approved v1.")
        result = prune.after_release(hw, "A", "v3", digest)
        self.assertEqual((result["status"], sorted(result["restored"])), ("refused", sorted(SUPERSEDED[:3])))
        self.assertEqual(result["plan"]["keep"]["v1"], ["named by DR-006"])
        self.assertGone(hw, SUPERSEDED, gone=False)
        for folder in ("versions/v1", "checks/v1/static", "renders/v1/iso"):
            self.assertEqual(layout.verify(hw / folder), [], folder)
        self.assertFalse(self.journal(hw, digest).parent.exists())

    def test_a_real_kept_manifest_that_references_a_superseded_version_keeps_it(self) -> None:
        hw = self.released()
        # a changed-only sweep of v3 names its baseline label in its recipe, as sweep.py records it
        publish(hw, "motion", "elbow-changed", {"result.json": '{"status": "pass"}\n'}, version="v3",
                recipe={"subject": "elbow-changed", "options": {"changed_only": {"baseline": "v2"}}})
        # a v3 check that reuses a v1 result names that bundle's manifest by its sha256
        reused = sha(hw / "checks" / "v1" / "static" / "manifest.json")
        publish(hw, "checks", "recheck", {"result.json": '{"status": "pass"}\n'}, version="v3",
                recipe={"subject": "recheck", "reused": {"manifest_sha256": reused}})
        plan = prune.plan(hw, "A", "v3")
        self.assertEqual(plan["prune"], [])
        self.assertEqual(plan["keep"]["v2"], ["referenced by hw/motion/v3/elbow-changed/manifest.json"])
        self.assertEqual(plan["keep"]["v1"], ["referenced by hw/checks/v3/recheck/manifest.json"])

    def test_a_symlinked_bundle_root_is_refused_in_the_plan(self) -> None:
        hw = self.released()
        elsewhere = self.root / "renders-v2"
        shutil.move(hw / "renders" / "v2", elsewhere)
        (hw / "renders" / "v2").symlink_to(elsewhere, target_is_directory=True)
        plan = prune.plan(hw, "A", "v3")
        self.assertEqual(plan["prune"], ["v1"])
        self.assertEqual(plan["keep"]["v2"], ["refused: hw/renders/v2 is a symbolic link; resolve it by hand to prune v2"])

    def test_plan_keeps_frozen_change_baseline_and_decision_milestones(self) -> None:
        hw = self.released(seal=False)
        write_test_decision(hw, "DR-006", context="The PARTS gate approved v1.")
        edit_yaml(hw / "product.yaml", lambda data: data["flow"].update(
            change={"decision": "DR-006", "baseline_version": "v2", "affected_parts": ["LMP-0001"]}))
        plan = prune.plan(hw, "A", "v3")
        self.assertEqual(plan["prune"], [])
        self.assertEqual(plan["keep"]["v1"], ["named by DR-006"])
        self.assertEqual(plan["keep"]["v2"], ["baseline of product.yaml flow.change"])
        for reason in ("frozen in product.yaml flow.frozen", "named by DR-005", "latest: versions/latest.json names it"):
            self.assertIn(reason, plan["keep"]["v3"])

    def test_a_stray_decision_file_that_names_a_version_still_keeps_it(self) -> None:
        hw = self.released(seal=False)
        removable = prune.plan(hw, "A", "v3")["prune"]
        self.assertIn("v1", removable, "v1 is removable before the stray file")
        for name in ("DR-007-Bad_Name.md", "DR-007.md"):
            with self.subTest(name):
                stray = hw / "decisions" / name
                write(stray, "Status: APPROVED\n\nThe PARTS gate approved v1.\n")
                plan = prune.plan(hw, "A", "v3")
                self.assertEqual(plan["prune"], [v for v in removable if v != "v1"])
                self.assertEqual(plan["keep"]["v1"], ["named by DR-007"])
                stray.unlink()

    def test_evidence_only_the_ledger_cites_keeps_its_version(self) -> None:
        hw = self.released()
        ledger = hw / "manufacturing" / "evidence.yaml"
        data = yaml.safe_load(ledger.read_text(encoding="utf-8"))
        data["entries"].append({"id": "EV-099", "requirement": "REQ-001", "subject": {"product": True}, "level": "cad_valid",
                                "result": "planned", "method": "TST re-run of the v2 sweep",
                                "note": "compare with hw/motion/v2/elbow-sweep"})
        ledger.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        plan = prune.plan(hw, "A", "v3")
        self.assertEqual(plan["prune"], ["v1"])
        self.assertEqual(plan["keep"]["v2"], ["referenced by hw/manufacturing/evidence.yaml"])

    def test_a_release_manifest_version_it_cannot_read_refuses_the_plan(self) -> None:
        hw = self.released()
        write(hw / "releases" / "B" / "manifest.json", json.dumps({"schema_version": 9, "product_id": "lamp-arm", "rev": "B"}))
        with self.assertRaisesRegex(layout.LayoutError, "manifest version 9"):
            prune.plan(hw, "A", "v3")

    def test_a_missing_or_older_release_manifest_schema_refuses_the_plan_and_changes_nothing(self) -> None:
        hw = self.released()
        manifest_path = hw / "releases" / "B" / "manifest.json"
        for label, document, named in (("missing schema", {"product_id": "lamp-arm", "rev": "B", "files": ["hw/bom.csv"]}, "None"),
                                       ("schema 2", {"schema_version": 2, "product_id": "lamp-arm", "rev": "B"}, "2")):
            with self.subTest(manifest=label):
                write(manifest_path, json.dumps(document))
                before = tree(hw)
                with self.assertRaisesRegex(layout.LayoutError, f"manifest version {named}"):
                    prune.plan(hw, "A", "v3")
                self.assertEqual(tree(hw), before, "a refused plan changes no file")


class Documents(ReleaseCase):
    def guide(self, hw: Path, *extra: str) -> None:
        result = subprocess.run([sys.executable, str(BUILD_GUIDE), str(hw), "--version", "v1", "--out", str(hw / "docs"),
                                 *extra], capture_output=True, text=True, timeout=300, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_package_okh_toml_describes_its_release(self) -> None:
        sealing = datetime(2026, 11, 2, 23, 59, 59, tzinfo=timezone.utc)  # a fixed clock: no UTC-midnight race
        hw = self.project()
        self.guide(hw)
        code, report = self.release(hw, now=sealing)
        self.assertEqual(code, 1)
        self.assertIn("release.docs", [item.get("code") for item in report["findings"]])
        self.assertFalse((hw / "releases").exists())
        self.guide(hw, "--rev", "A", "--date", "2026-11-02")
        code, report = self.release(hw, now=sealing + timedelta(seconds=2))  # the next UTC day
        self.assertEqual(code, 1)
        self.assertIn("dated 2026-11-03", json.dumps(report["findings"]))
        code, report = self.release(hw, now=sealing)
        self.assertEqual(code, 0, report.get("findings"))
        okh = tomllib.loads((hw / "releases" / "A" / "docs" / "okh.toml").read_text(encoding="utf-8"))["okhv"]
        manifest = json.loads((hw / "releases" / "A" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["released_at"], "2026-11-02T23:59:59Z")
        self.assertEqual({key: okh[key] for key in ("version", "release", "release_date")},
                         {"version": "v1", "release": "A", "release_date": "2026-11-02"})

    def test_a_next_day_repair_keeps_the_release_date(self) -> None:
        sealing = datetime(2026, 11, 2, 23, 59, 59, tzinfo=timezone.utc)
        hw = self.project()
        self.guide(hw, "--rev", "A", "--date", "2026-11-02")
        self.assertEqual(self.release(hw, now=sealing)[0], 0)
        write(hw / "releases" / "A" / "bom.csv", "edited\n")
        code, report = self.release(hw, now=sealing + timedelta(days=1))
        self.assertEqual(code, 0, report.get("findings"))
        okh = tomllib.loads((hw / "releases" / "A" / "docs" / "okh.toml").read_text(encoding="utf-8"))["okhv"]
        manifest = json.loads((hw / "releases" / "A" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["released_at"], okh["release_date"]), ("2026-11-02T23:59:59Z", "2026-11-02"))
        self.guide(hw, "--rev", "A", "--date", "2026-11-02")  # build_guide.py refuses any date but the sealed one


class Refusal(ReleaseCase):
    """Each gap refuses with a finding that names it, and hw/ is byte-identical afterwards."""

    def refused(self, hw: Path, path: str, code: str, text: str, **arguments: str) -> None:
        before = tree(hw)
        result, report = self.release(hw, **arguments)
        self.assertEqual((result, report["status"]), (1, "refused"))
        self.assertTrue(any(item["path"] == path and item.get("code") == f"release.{code}" and text in item["message"]
                            for item in report["findings"]), json.dumps(report["findings"], indent=1))
        self.assertEqual(tree(hw), before, "a refused release writes nothing in hw/")

    def test_a_missing_fdm_stl_refuses(self) -> None:
        hw = self.project(omit=(("LMP-0001", "part.stl"),))
        self.refused(hw, "hw/versions/v1/manufacturing/LMP-0001/part.stl", "missing",
                     "a fdm part needs part.step, part.stl, part.3mf")

    def test_a_missing_fdm_3mf_refuses(self) -> None:
        hw = self.project(omit=(("LMP-0001", "part.3mf"),))
        self.refused(hw, "hw/versions/v1/manufacturing/LMP-0001/part.3mf", "missing",
                     "a fdm part needs part.step, part.stl, part.3mf")
        self.assertFalse((hw / "releases").exists())

    def test_a_failed_manufacturing_check_refuses(self) -> None:
        hw = self.project(failed={"LMP-0004": "bed_contact"})
        self.refused(hw, "hw/versions/v1/manufacturing/LMP-0004/manufacturing.json", "failed", "bed_contact failed")

    def test_a_bundle_with_a_changed_member_is_stale_and_refuses(self) -> None:
        hw = self.project()
        write(hw / "drawings" / "v1" / "LMP-0002" / "sheet-1.svg", "edited\n")
        self.refused(hw, "hw/drawings/v1/LMP-0002", "stale", "stale: sheet-1.svg changed after it was sealed")

    def test_a_bundle_with_a_missing_member_is_stale_and_refuses(self) -> None:
        hw = self.project()
        (hw / "drawings" / "v1" / "LMP-0002" / "sheet-1.svg").unlink()
        self.refused(hw, "hw/drawings/v1/LMP-0002", "stale", "stale: sheet-1.svg is listed but missing")

    def test_a_bundle_whose_manifest_names_another_layout_or_path_is_stale_and_refuses(self) -> None:
        for field, value in (("layout", "bundle.renders"), ("path", "hw/drawings/v1/LMP-0003")):
            with self.subTest(field):
                hw = self.project()
                path = hw / "drawings" / "v1" / "LMP-0002" / "manifest.json"
                manifest = json.loads(path.read_text(encoding="utf-8"))
                manifest[field] = value
                path.write_text(json.dumps(manifest), encoding="utf-8")
                named = {"layout": (value, manifest["path"]), "path": (manifest["layout"], value)}[field]
                self.refused(hw, "hw/drawings/v1/LMP-0002", "stale", f"stale: manifest.json names {named[0]} at {named[1]}")
                self.assertFalse((hw / "releases").exists())

    def test_a_source_that_changes_while_it_is_copied_is_stale_and_refuses(self) -> None:
        hw = self.project()
        real, drifted = release.shutil.copyfile, []

        def drift_then_copy(source: Any, target: Any, **options: Any) -> Any:
            if not drifted:  # the first source changes after it was checked and before it is copied
                drifted.append(Path(source))
                Path(source).chmod(0o644)
                Path(source).write_text("drifted\n", encoding="utf-8")
            return real(source, target, **options)

        with mock.patch.object(release.shutil, "copyfile", drift_then_copy):
            result, report = self.release(hw)
        original = drifted[0].relative_to(hw.resolve().parent).as_posix()
        self.assertEqual((result, report["status"]), (1, "refused"))
        self.assertTrue(any(item["path"] == original and item.get("code") == "release.stale"
                            and item["message"] == f"stale: {original} changed since it was checked"
                            for item in report["findings"]), json.dumps(report["findings"], indent=1))
        self.assertFalse((hw / "releases").exists())

    def test_a_staged_package_that_fails_its_seal_is_stale_and_refuses(self) -> None:
        hw = self.project()
        real = release.validate.validate_document

        def validate_then_add_a_stray_file(*arguments: Any, **options: Any) -> Any:
            found = real(*arguments, **options)
            for staged in (hw.parent / ".cad-work" / "release-A").glob("stage-*"):
                write(staged / "stray.txt")
            return found

        with mock.patch.object(release.validate, "validate_document", validate_then_add_a_stray_file):
            result, report = self.release(hw)
        self.assertEqual((result, report["status"]), (1, "refused"))
        self.assertTrue(any(item.get("code") == "release.stale" and item["message"] == "stale: stray.txt is not in the manifest"
                            for item in report["findings"]), json.dumps(report["findings"], indent=1))
        self.assertFalse((hw / "releases").exists())

    def test_a_missing_drawing_refuses(self) -> None:
        hw = self.project(skip_bundles=("LMP-0006",))
        self.refused(hw, "hw/drawings/v1/LMP-0006", "missing", "LMP-0006 declares drawing intent")

    def test_a_changed_current_record_refuses(self) -> None:
        hw = self.project()
        edit_yaml(hw / "parts" / "LMP-0003" / "part.yaml", lambda data: data.update(finish="Anodized"))
        self.refused(hw, "hw/parts/LMP-0003/part.yaml", "changed", "differs from v1/record/parts/LMP-0003/part.yaml")
        hw = self.project()
        model = hw / "parts" / "LMP-0002" / "model.py"
        model.write_text(model.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
        self.refused(hw, "hw/parts/LMP-0002/model.py", "changed", "is not the model v1 built")

    def test_a_wrong_version_refuses(self) -> None:
        hw = self.project()
        self.refused(hw, "hw/product.yaml", "frozen", "flow.frozen names v1, not v2", version="v2")

    def test_the_same_revision_with_an_equal_frozen_manifest_is_rewritten_byte_identically(self) -> None:
        hw = self.project()
        first_code, first = self.release(hw, now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc))
        self.assertEqual(first_code, 0)
        before = tree(hw)
        code, report = self.release(hw, now=datetime(2026, 6, 7, 8, 9, 10, tzinfo=timezone.utc))
        self.assertEqual((code, report["status"], report["manifest_sha256"]), (0, "released", first["manifest_sha256"]))
        self.assertEqual(tree(hw), before, "the rerun leaves the package byte-identical")

    def test_a_stale_package_of_another_approval_needs_a_new_revision(self) -> None:
        hw = self.project()
        self.assertEqual(self.release(hw)[0], 0)
        write(hw / "releases" / "A" / "bom.csv", "edited\n")
        self.refused(hw, "hw/releases/A", "stale", "automatic repair is not supported; use a new revision",
                     decision="DR-004")

    def test_a_stale_package_of_another_frozen_manifest_needs_a_new_revision(self) -> None:
        hw = self.project()
        self.assertEqual(self.release(hw)[0], 0)
        write(hw / "releases" / "A" / "bom.csv", "edited\n")
        manifest = hw / "versions" / "v1" / "manifest.json"
        manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.refused(hw, "hw/releases/A", "stale", "stale: bom.csv changed after it was sealed")
        self.refused(hw, "hw/releases/A", "stale", "automatic repair is not supported; use a new revision")

    def test_a_changed_frozen_manifest_under_the_same_revision_needs_a_new_revision(self) -> None:
        hw = self.project()
        self.assertEqual(self.release(hw)[0], 0)
        manifest = hw / "versions" / "v1" / "manifest.json"
        manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.refused(hw, "hw/releases/A", "exists", "automatic repair is not supported; use a new revision")

    def test_a_rerun_from_a_version_that_fails_its_manifest_is_refused_and_changes_nothing(self) -> None:
        hw = self.project()
        self.assertEqual(self.release(hw)[0], 0)
        (hw / "versions" / "v1" / "assembly.glb").unlink()
        self.refused(hw, "hw/releases/A", "exists", "automatic repair is not supported; use a new revision")

    def test_the_atomic_claim_refuses_a_writer_that_loses_the_race(self) -> None:
        hw = self.project()
        real_claim = release.layout.claim

        def rival_first(staged: Path, target: Path, target_rel: str) -> None:
            target.mkdir(parents=True)  # another writer holds the revision before this one claims it
            real_claim(staged, target, target_rel)

        with mock.patch.object(release.layout, "claim", rival_first):
            code, report = self.release(hw)
        self.assertEqual((code, report["status"]), (1, "refused"))
        self.assertIn("another writer published hw/releases/A first", report["findings"][0]["message"])
        self.assertEqual(list((hw / "releases" / "A").iterdir()), [], "the loser published nothing")

    def test_a_missing_decision_refuses(self) -> None:
        hw = self.project()
        self.refused(hw, "hw/decisions", "decision", "DR-099 has no record: expected hw/decisions/DR-099-<slug>.md",
                     decision="DR-099")

    def test_only_an_accepted_decision_approves_a_release(self) -> None:
        hw = self.project()
        for status in ("proposed", "rejected", "deprecated"):
            with self.subTest(status=status):
                write_test_decision(hw, "DR-006", status=status)
                self.refused(hw, "hw/decisions/DR-006-test-decision-dr-006.md", "decision",
                             f"DR-006 has status {status}, not the user's approval (accepted)", decision="DR-006")
        write_test_decision(hw, "DR-006", context="The user approved v1 as A.")
        result, report = self.release(hw, decision="DR-006")
        self.assertEqual((result, report["status"]), (0, "released"), report.get("findings"))

    def test_a_release_decision_the_reader_refuses_or_in_the_old_form_is_no_approval(self) -> None:
        hw = self.project()
        record = write_test_decision(hw, "DR-006")  # complete in every section but the status below
        record.write_text(record.read_text(encoding="utf-8").replace("status: accepted", "status: approved", 1),
                          encoding="utf-8")
        self.refused(hw, f"hw/decisions/{record.name}", "decision", "status 'approved'", decision="DR-006")
        record.unlink()
        write(hw / "decisions" / "DR-006.md", "Status: APPROVED\n\n# DR-006 Release A\n")
        self.refused(hw, "hw/decisions", "decision", "DR-006 has no record: expected hw/decisions/DR-006-<slug>.md",
                     decision="DR-006")

    def test_a_freeze_on_a_proposed_decision_refuses_the_release(self) -> None:
        hw = self.project()
        record = decision_path(hw, "DR-004")
        write(record, record.read_text(encoding="utf-8").replace("status: accepted", "status: proposed", 1))
        before = tree(hw)
        result, report = self.release(hw)
        self.assertEqual((result, report["status"]), (1, "refused"))
        self.assertTrue(any("flow/frozen/decision DR-004 has status proposed" in item["message"]
                            for item in report["findings"]), json.dumps(report["findings"], indent=1))
        self.assertEqual(tree(hw), before)

    def test_unverified_requirements_and_missing_evidence_refuse(self) -> None:
        hw = self.project()
        edit_csv(hw / "verification.csv", lambda rows: rows[0].update(result="planned"))
        before = tree(hw)
        code, report = self.release(hw)
        self.assertEqual(code, 1)
        self.assertIn("release verification result must be pass or waived", json.dumps(report["findings"]))
        self.assertEqual(tree(hw), before)
        hw = self.project()
        edit_csv(hw / "verification.csv", lambda rows: rows[1].update(evidence="hw/motion/v1/elbow-limits"))
        self.refused(hw, "hw/motion/v1/elbow-limits", "missing", "REQ-002 cites it")

    def test_cited_evidence_inside_the_frozen_version_or_a_bundle_must_exist(self) -> None:
        for evidence in ("hw/analysis/v1/arm-load/result.json", "hw/versions/v1/x.step"):
            with self.subTest(evidence=evidence):
                hw = self.project()
                edit_csv(hw / "verification.csv", lambda rows: [row.update(evidence=evidence) for row in rows
                                                                if row["requirement_id"] == "REQ-004"])
                with (hw / "verification.csv").open(newline="", encoding="utf-8") as stream:
                    line = next(n for n, row in enumerate(csv.DictReader(stream), start=2) if row["requirement_id"] == "REQ-004")
                self.refused(hw, f"hw/verification.csv:{line}", "missing", f"REQ-004 evidence {evidence} does not exist")

    def test_a_bad_argument_is_a_usage_error(self) -> None:
        hw = self.project()
        result = subprocess.run([sys.executable, str(RELEASE), str(hw), "--rev", "I", "--version", "v1",
                                 "--decision", "DR-005"], capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("REV 'I' does not match", json.loads(result.stdout)["message"])


DAMAGE: dict[str, Callable[[Path], Any]] = {  # ways a sealed package fails its seal, each applied to hw/releases/A
    "a changed file": lambda package: write(package / "bom.csv", "edited\n"),
    "a missing file": lambda package: (package / "verification.csv").unlink(),
    "an extra file": lambda package: write(package / "stray.txt"),
}


class Repair(ReleaseCase):
    """A stale hw/releases/<REV>/ of the same version, approval and frozen manifest is sealed again from that
    frozen manifest, under the revision's lock, and a failed attempt leaves the stale package where it was."""

    def released(self) -> tuple[Path, dict[str, str]]:
        hw = self.project()
        code, report = self.release(hw)
        self.assertEqual(code, 0, report.get("findings"))
        return hw, tree(hw / "releases" / "A")

    def lock_held(self, hw: Path) -> bool:
        """Whether a writer holds the lock of hw/releases/A: a second open file cannot take it."""
        lock = layout._lock_path(hw, "hw/releases/A")
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("a") as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(probe, fcntl.LOCK_UN)
            return False

    def replaced(self, hw: Path) -> list[Path]:
        """The packages a run moved aside, under .cad-work/replaced/."""
        root = hw.parent / ".cad-work" / "replaced" / "hw" / "releases" / "A"
        return sorted(root.iterdir()) if root.is_dir() else []

    def test_a_stale_package_of_the_same_frozen_manifest_is_sealed_again_byte_identically(self) -> None:
        for damage, spoil in DAMAGE.items():
            with self.subTest(damage):
                hw, sealed = self.released()
                spoil(hw / "releases" / "A")
                stale = tree(hw / "releases" / "A")
                code, report = self.release(hw)
                self.assertEqual((code, report["status"]), (0, "released"), report.get("findings"))
                self.assertEqual(tree(hw / "releases" / "A"), sealed, "the repair seals the same package again")
                self.assertEqual([tree(path) for path in self.replaced(hw)], [stale], "the stale package is kept aside")

    def test_seal_findings_outside_the_repaired_package_still_refuse(self) -> None:
        for damage, code in (("a missing file", "layout.missing"), ("an extra file", "layout.unlisted")):
            with self.subTest(damage):
                hw, _ = self.released()
                shutil.copytree(hw / "releases" / "A", hw / "releases" / "B")  # another sealed package
                DAMAGE[damage](hw / "releases" / "B")
                DAMAGE["a changed file"](hw / "releases" / "A")
                before = tree(hw)
                result, report = self.release(hw)
                self.assertEqual((result, report["status"]), (1, "refused"))
                other = hw.resolve() / "releases" / "B"
                self.assertTrue(any(item.get("code") == code and Path(item["path"]).is_relative_to(other)
                                    for item in report["findings"]), json.dumps(report["findings"], indent=1))
                self.assertEqual(tree(hw), before)

    def overlap(self, hw: Path, at: tuple[Any, str], b_work: Callable[[], Any] | None = None,
                then: Callable[[], Any] = lambda: None, a_decision: str = "DR-005") -> Overlap:
        """Overlap.run on hw/releases/A: writer A releases, approved by `a_decision`, and writer B runs
        `b_work` (a release by default). B's first lock attempt finds the revision's lock taken, and B
        inspects, validates and stages nothing before it."""
        race = Overlap(self, hw, at, then)
        race.run(lambda: self.release(hw, decision=a_decision), b_work or (lambda: self.release(hw)))
        self.assertTrue(race.blocked, "B's first lock attempt finds the revision's lock taken")
        self.assertEqual(race.before_lock, [], "B inspects, validates and stages nothing before it holds the lock")
        return race

    def assert_repaired_once(self, hw: Path, sealed: dict[str, str], race: Overlap) -> None:
        """A repaired the stale package; B then found it sealed and was a no-op that left nothing behind."""
        a, b = race.outcome["a"], race.outcome["b"]
        self.assertEqual(a[0], 0, a)
        self.assertEqual((b[0], b[1].get("already_sealed")), (0, True), b)
        self.assertNotIn("stage", race.calls, "B found the package sealed and staged nothing")
        self.assertEqual(tree(hw / "releases" / "A"), sealed, "A's repair is in place")
        moved = self.replaced(hw)
        self.assertEqual(len(moved), 1, "only A moved a package aside")
        self.assertTrue(all(layout.verify(path) for path in moved), "no sound package was moved aside")
        self.assertEqual(sorted((hw.parent / ".cad-work" / "release-A").glob("stage-*")), [], "no stage is left")

    def test_a_slower_writer_never_moves_a_repaired_package_aside(self) -> None:
        hw, sealed = self.released()
        DAMAGE["a changed file"](hw / "releases" / "A")
        held: list[bool] = []
        probe = on_thread("writer-a", release.layout.claim, lambda: held.append(self.lock_held(hw)))
        with mock.patch.object(release.layout, "claim", probe):
            race = self.overlap(hw, (release, "stage"))  # A pauses once it has staged its repair
        self.assert_repaired_once(hw, sealed, race)
        self.assertTrue(held and all(held), "every claim ran under the revision's lock")

    def test_a_repair_judges_a_waiver_on_the_release_date(self) -> None:
        sealing, later = (datetime(2026, 2, 27, 12, tzinfo=timezone.utc), datetime(2026, 4, 1, 12, tzinfo=timezone.utc))
        with fixed_today(sealing.date()):  # the waivers hold until 2026-03-01
            hw = self.project(service_class="fit_assembly", ledger=waive_fdm_trials_until("2026-03-01"))
            code, report = self.release(hw, now=sealing)
        self.assertEqual(code, 0, report.get("findings"))
        sealed = tree(hw / "releases" / "A")
        DAMAGE["a changed file"](hw / "releases" / "A")
        with fixed_today(later.date()):
            self.assertIn("waiver.expired", json.dumps(validate.validate_project(hw)), "the waivers expired by today")
            code, report = self.release(hw, now=later)
        self.assertEqual(code, 0, report.get("findings"))
        self.assertEqual(tree(hw / "releases" / "A"), sealed, "the repair seals the package of the release date again")

    def test_a_writer_that_finds_another_package_under_the_lock_leaves_no_stage(self) -> None:
        cases = {  # the revision when B starts, A's approval, and B's outcome once A has sealed the revision
            "a repair, then A's repair": ("stale", "DR-005", (0, "released")),
            "a fresh release, then A's release": ("absent", "DR-005", (0, "released")),
            "a fresh release, then A's release of another approval": ("absent", "DR-004", (1, "refused")),
        }
        for case, (revision, a_decision, expected) in cases.items():
            with self.subTest(case):
                if revision == "stale":
                    hw, _ = self.released()
                    DAMAGE["a changed file"](hw / "releases" / "A")
                else:
                    hw = self.project()
                race = self.overlap(hw, (release, "stage"), a_decision=a_decision)
                code, report = race.outcome["b"]
                self.assertEqual(((code, report["status"]), report.get("stage")), (expected, None), report)
                stages = sorted((hw.parent / ".cad-work" / "release-A").glob("stage-*"))
                self.assertEqual(stages, [], "the losing writer left no stage")

    def test_a_writer_that_starts_during_a_repair_waits_for_it_and_finds_it_sealed(self) -> None:
        hw, sealed = self.released()
        DAMAGE["a changed file"](hw / "releases" / "A")
        race = self.overlap(hw, (release.layout, "claim"))  # A has moved the stale package aside, not claimed yet
        self.assert_repaired_once(hw, sealed, race)

    def test_a_writer_that_starts_during_a_repairs_validation_waits_for_it(self) -> None:
        hw, sealed = self.released()
        DAMAGE["a changed file"](hw / "releases" / "A")
        race = self.overlap(hw, (release.validate, "validate_project"))  # A is in assemble's project validation
        self.assert_repaired_once(hw, sealed, race)

    def test_prune_during_a_repair_whose_claim_fails_refuses_and_repairs_nothing(self) -> None:
        hw, _ = self.released()
        DAMAGE["a changed file"](hw / "releases" / "A")
        before = tree(hw)

        def claim_fails() -> None:
            raise PermissionError(13, "Permission denied")

        race = self.overlap(hw, (release.layout, "claim"), b_work=lambda: cli(hw, "--prune"), then=claim_fails)
        self.assertIsInstance(race.outcome["a"], layout.LayoutError, "A's claim failed and A put the package back")
        code, report = race.outcome["b"]
        self.assertEqual((code, report["status"]), (1, "refused"), report)
        self.assertEqual(report["findings"][0]["code"], "release.stale")
        self.assertEqual(tree(hw), before, "prune repaired nothing and deleted nothing")

    def test_a_run_takes_the_revisions_lock_once(self) -> None:
        for case in ("a fresh release", "a repair", "--prune on a stale package"):
            with self.subTest(case):
                if case == "a fresh release":
                    hw = self.project()
                else:
                    hw, _ = self.released()
                    DAMAGE["a changed file"](hw / "releases" / "A")
                taken: list[str] = []
                counted = on_thread(threading.current_thread().name, release.layout.target_lock,
                                    lambda: taken.append("lock"))
                with mock.patch.object(release.layout, "target_lock", counted):
                    cli(hw, "--prune") if case.startswith("--prune") else self.release(hw)
                self.assertEqual(taken, ["lock"], "one run takes the revision's lock exactly once")

    def test_a_failed_repair_puts_the_stale_package_back(self) -> None:
        failures = {  # the os call that fails inside the claim, and how it fails
            "an OSError from the claim's mkdir": ("mkdir", PermissionError(13, "Permission denied")),
            "a failed rename onto the claim": ("rename", OSError(18, "Cross-device link")),
        }
        for name, (call, failure) in failures.items():
            with self.subTest(name):
                hw, _ = self.released()
                DAMAGE["a changed file"](hw / "releases" / "A")
                before = tree(hw)
                real_claim, claims = release.layout.claim, []

                def failing_claim(staged: Path, target: Path, target_rel: str) -> None:
                    claims.append(staged)
                    if len(claims) > 1:  # putting the stale package back
                        return real_claim(staged, target, target_rel)
                    with mock.patch.object(layout.os, call, side_effect=failure):
                        return real_claim(staged, target, target_rel)

                with mock.patch.object(release.layout, "claim", failing_claim):
                    with self.assertRaises(layout.LayoutError) as caught:  # an infrastructure error: exit 2
                        self.release(hw)
                self.assertIn(failure.strerror, str(caught.exception))
                self.assertIn("the stale package it replaced is back in place", str(caught.exception))
                self.assertEqual(tree(hw), before, "the stale package is back where it was")

    def test_a_failed_repair_never_replaces_another_writers_package(self) -> None:
        hw, _ = self.released()
        DAMAGE["a changed file"](hw / "releases" / "A")
        real_claim = release.layout.claim
        package = hw / "releases" / "A"

        def rival_first(staged: Path, target: Path, target_rel: str) -> None:
            if not (target / "rival.txt").exists():  # another writer lands at the revision before this claim
                write(target / "rival.txt", "another writer\n")
            real_claim(staged, target, target_rel)

        with mock.patch.object(release.layout, "claim", rival_first):
            code, report = self.release(hw)
        self.assertEqual((code, report["status"]), (1, "refused"))
        self.assertEqual(sorted(path.name for path in package.iterdir()), ["rival.txt"], "the other writer's package stays")
        moved = self.replaced(hw)
        self.assertEqual(len(moved), 1)
        self.assertEqual((moved[0] / "bom.csv").read_text(encoding="utf-8"), "edited\n", "the stale package is kept")
        self.assertIn(layout.relative(hw, moved[0]), json.dumps(report["findings"]))


def waive_fdm_trials(hw: Path, record: Any, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The accepted entries plus an approved, scoped trial waiver (DR-006) for every FDM part's print trial, and
    accepted joint evidence (a TST retention test) for every assembly.joint obligation: a fit-assembly release
    resolves the joints, which assembly_operations judges unknown from this record's unsourced heat-set facts."""
    acceptance.decision(hw, "DR-006")
    configuration = entries[0]["configuration"]
    for obligation in acceptance.mi.required_checks(record):
        subject = dict(obligation.subject)
        if obligation.family == "process.fdm.trial":
            entries.append(acceptance.entry(record, f"EV-{len(entries) + 1:03d}", subject, "physically_validated", "waived",
                                            obligation=obligation.id,
                                            waiver=acceptance.waiver(subject, "DR-006", obligation=obligation.id)))
        elif obligation.family == "assembly.joint":
            entries.append(acceptance.entry(record, f"EV-{len(entries) + 1:03d}", subject, obligation.level,
                                            obligation=obligation.id, version=configuration["version"],
                                            manifest_sha256=configuration["manifest_sha256"],
                                            geometry=impact.current_geometry(hw), artifacts=["hw/docs/inspection.md"], hw=hw))
    return entries


def on_thread(name: str, real: Callable[..., Any], before: Callable[[], Any]) -> Callable[..., Any]:
    """`real`, calling `before` first when the thread named `name` calls it."""
    def call(*arguments: Any, **options: Any) -> Any:
        if threading.current_thread().name == name:
            before()
        return real(*arguments, **options)
    return call


def cli(hw: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    """release.py's main for revision A of v1, approved by DR-005, in this process: its exit code and report."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = release.main([str(hw), "--rev", "A", "--version", "v1", "--decision", "DR-005", *extra])
    return code, json.loads(out.getvalue())


class Overlap:
    """Two writers of one revision in threads, steered by events and never by timing. Writer A runs first
    and pauses at its first call of `at` (an object and an attribute name), then calls `then` (which may
    raise) before the real call. Writer B starts while A is paused. At B's first lock attempt, `blocked`
    records whether the revision's lock was taken, and `before_lock` the watched calls B had made by then.
    A goes on from there. `outcome` holds each writer's result or exception, `calls` all of B's watched calls."""

    GUARD = 30  # seconds: only a hang guard, never part of the logic
    WATCHED = ((release, "existing"), (release, "stage"), (release.validate, "validate_project"))

    def __init__(self, case: Any, hw: Path, at: tuple[Any, str], then: Callable[[], Any]) -> None:
        self.case, self.hw, self.at, self.then = case, hw, at, then
        self.paused, self.go, self.settled = threading.Event(), threading.Event(), threading.Event()
        self.outcome: dict[str, Any] = {}
        self.calls: list[str] = []
        self.blocked: bool | None = None
        self.before_lock: list[str] | None = None

    def pause(self) -> None:
        if not self.paused.is_set():
            self.paused.set()
            self.go.wait(self.GUARD)
            self.then()

    def b_locks(self) -> None:
        if self.blocked is None:
            self.blocked, self.before_lock = self.case.lock_held(self.hw), list(self.calls)
            self.settled.set()

    def writer(self, name: str, work: Callable[[], Any]) -> threading.Thread:
        def body() -> None:
            try:
                self.outcome[name] = work()
            except BaseException as error:  # the test reads it
                self.outcome[name] = error
            self.settled.set()  # a writer that ends without a lock attempt settles the wait too
        return threading.Thread(target=body, name=f"writer-{name}", daemon=True)

    def run(self, a_work: Callable[[], Any], b_work: Callable[[], Any]) -> None:
        target, name = self.at
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(target, name, on_thread("writer-a", getattr(target, name), self.pause)))
            stack.enter_context(mock.patch.object(release.layout, "target_lock",
                                                  on_thread("writer-b", release.layout.target_lock, self.b_locks)))
            for owner, attribute in self.WATCHED:
                stack.enter_context(mock.patch.object(owner, attribute, on_thread(
                    "writer-b", getattr(owner, attribute), lambda attribute=attribute: self.calls.append(attribute))))
            a, b = self.writer("a", a_work), self.writer("b", b_work)
            a.start()
            try:
                self.case.assertTrue(self.paused.wait(self.GUARD), f"writer A never reached its pause: {self.outcome}")
                b.start()
                self.case.assertTrue(self.settled.wait(self.GUARD), "writer B never reached the lock")
            finally:
                self.go.set()
                a.join(self.GUARD)
            b.join(self.GUARD)
        self.case.assertFalse(a.is_alive() or b.is_alive(), "a writer hung")


def waive_fdm_trials_until(expires: str) -> Callable[[Path, Any, list[dict[str, Any]]], list[dict[str, Any]]]:
    """waive_fdm_trials, each waiver expiring on `expires` (YYYY-MM-DD)."""
    def ledger(hw: Path, record: Any, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        entries = waive_fdm_trials(hw, record, entries)
        for entry in entries:
            if entry.get("result") == "waived":
                entry["waiver"]["expires"] = expires
        return entries
    return ledger


def fixed_today(day: date) -> Any:
    """A patch of evidence.py's clock: date.today() is `day` while it is active."""
    class Fixed(date):
        @classmethod
        def today(cls) -> Fixed:
            return cls(day.year, day.month, day.day)
    return mock.patch.object(release.evidence, "date", Fixed)


def open_selection(hw: Path) -> None:
    """selection.yaml assessing one candidate for LMP-0001 (its recorded FDM route, no material profile, so
    the capability's material approval stays unknown: conditional), on a digest of other inputs (stale)."""
    candidate = {"id": "lamp_as_drawn", "title": "TST: the base as drawn", "architecture": "TST: as recorded",
                 "parts": [{"PN": "LMP-0001", "material_profile": fx.not_applicable(acceptance.NA),
                            "route": [{"kind": "fdm", "capability": "tst_fdm"}]}],
                 "evaluations": [], "pros": ["TST: as drawn"], "cons": ["TST: none recorded"], "tradeoffs": ["TST: none"]}
    write(hw / "manufacturing" / "selection.yaml", yaml.safe_dump({
        "status": "assessed", "assessment": {"input_sha256": "0" * 64, "method": "selection.py", "date": "2026-01-01"},
        "candidates": [candidate]}, sort_keys=False))


class Acceptance(ReleaseCase):
    """The intent acceptance of a record version 2 release: anchor, evidence and service policy."""

    def test_a_record_without_the_current_version_refuses(self) -> None:
        hw = self.project()
        edit_yaml(hw / "product.yaml", lambda data: data.pop("record_version"))
        before = tree(hw)
        code, report = self.release(hw)
        self.assertEqual((code, report["status"]), (1, "refused"))
        self.assertIn("record.version_unsupported", [item.get("code") for item in report["findings"]])
        self.assertEqual(tree(hw), before)

    def test_a_freeze_without_an_acceptance_anchor_refuses(self) -> None:
        hw = self.project(anchor=False)
        self.assertEqual(validate.blocking(validate.validate_project(hw)), [], "readable: only the release refuses an unanchored freeze")
        self.refused_with(hw, "release.frozen", "anchors no evidence_sha256")

    def test_evidence_accepted_after_the_freeze_needs_a_new_anchor(self) -> None:
        hw = self.project()
        ledger = hw / "manufacturing" / "evidence.yaml"
        data = yaml.safe_load(ledger.read_text(encoding="utf-8"))
        data["entries"].append({"id": "EV-099", "requirement": "REQ-001", "subject": {"product": True}, "level": "cad_valid",
                                "result": "planned", "method": "TST late plan"})
        ledger.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        self.assertIn("record.evidence_anchor", [item.get("code") for item in validate.validate_project(hw)])
        self.refused_with(hw, "release.acceptance", "not the acceptance digest")
        anchor = acceptance.freeze_anchor(hw, "v1")
        edit_yaml(hw / "product.yaml", lambda product: product["flow"]["frozen"].update(evidence_sha256=anchor))
        code, report = self.release(hw)
        self.assertEqual(code, 0, report.get("findings"))

    def test_a_verification_pass_without_ledger_evidence_refuses(self) -> None:
        hw = self.project(ledger=lambda hw, record, entries: [])
        self.refused_with(hw, "evidence.csv_unsupported", "a CSV result is a summary of accepted evidence")

    def test_an_untested_fit_prototype_refuses_and_approved_waivers_make_it_an_unvalidated_trial(self) -> None:
        hw = self.project(service_class="fit_assembly")
        self.refused_with(hw, "release.acceptance", "process.fdm.trial@LMP-0001/make is unknown")
        hw = self.project(service_class="fit_assembly", ledger=waive_fdm_trials)
        code, report = self.release(hw)
        self.assertEqual(code, 0, report.get("findings"))
        manifest = json.loads((hw / "releases" / "A" / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["acceptance"]["scope"]["trial"])
        self.assertEqual(manifest["checks"]["acceptance"], "waived")
        self.assertEqual({waiver["decision"] for waiver in manifest["acceptance"]["waivers"]}, {"DR-006"})
        self.assertIn("process.fdm.trial@LMP-0001/make", manifest["acceptance"]["open_obligations"])
        self.assertNotIn("physically_validated", manifest["acceptance"]["claims"]["REQ-001"])

    def test_a_production_release_is_never_a_waived_trial(self) -> None:
        hw = self.project(service_class="production", ledger=waive_fdm_trials)
        self.refused_with(hw, "release.acceptance", "release.trial_not_permitted")

    def test_a_sealed_package_is_verified_and_any_other_manifest_version_is_refused(self) -> None:
        hw = self.project()
        self.assertEqual(self.release(hw)[0], 0)
        code, report = release.sealed(hw, "A", "v1", "DR-005")
        self.assertEqual((code, report["manifest_version"]), (0, 3))
        path = hw / "releases" / "A" / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        forged = {**manifest, "acceptance": {**manifest["acceptance"], "evidence_sha256": "0" * 64}}
        path.write_text(json.dumps(forged), encoding="utf-8")
        code, report = release.sealed(hw, "A", "v1", "DR-005")
        self.assertEqual(code, 1)
        self.assertIn("not the digest of its sealed inventory", report["findings"][0]["message"])
        path.write_text(json.dumps({**manifest, "schema_version": 2}), encoding="utf-8")
        code, report = release.sealed(hw, "A", "v1", "DR-005")
        self.assertEqual(code, 1)
        self.assertIn("its manifest version 2 is not one this release.py reads", report["findings"][0]["message"])

    def test_a_sealed_package_with_a_changed_member_is_stale_not_sealed(self) -> None:
        hw = self.project()
        self.assertEqual(self.release(hw)[0], 0)
        member = next(p for p in sorted((hw / "releases" / "A").rglob("*")) if p.is_file() and p.name != "manifest.json")
        member.write_text("edited\n", encoding="utf-8")
        code, report = release.sealed(hw, "A", "v1", "DR-005")
        finding = report["findings"][0]
        self.assertEqual((code, report["status"], finding["code"]), (1, "refused", "release.stale"))
        self.assertTrue(finding["message"].startswith("stale: "), finding["message"])
        self.assertIn(f"{member.relative_to(hw / 'releases' / 'A').as_posix()} changed after it was sealed", finding["message"])

    def test_an_open_or_stale_selection_refuses_the_release(self) -> None:
        hw = self.project(before_build=open_selection)
        self.assertEqual(validate.blocking(validate.validate_project(hw)), [], "the record itself is valid")
        before = tree(hw)
        result, report = self.release(hw)
        self.assertEqual((result, report["status"]), (1, "refused"))
        messages = [item["message"] for item in report["findings"] if item.get("code") == "release.acceptance"]
        for text in ("gate.selection: the recorded assessed assessment is stale",
                     "gate.selection: the selection is conditional"):
            self.assertTrue(any(text in message for message in messages), messages)
        self.assertEqual(tree(hw), before, "a refused release writes nothing in hw/")

    def refused_with(self, hw: Path, code: str, text: str) -> None:
        before = tree(hw)
        result, report = self.release(hw)
        self.assertEqual((result, report["status"]), (1, "refused"))
        self.assertTrue(any((item.get("code") == code or code in item["message"]) and text in item["message"]
                            for item in report["findings"]), json.dumps(report["findings"], indent=1))
        self.assertEqual(tree(hw), before, "a refused release writes nothing in hw/")


class GuidelineEditsAfterTheFreeze(ReleaseCase):
    """A guideline set that applies to a part is part of what the freeze sealed: editing one makes `check_acceptance`
    refuse the release, with stale evidence for that part (benchhand-tw6.7)."""

    @staticmethod
    def guideline(minimum: float) -> str:
        return yaml.safe_dump({
            "schema_version": 1, "id": "fdm.generic", "revision": 1, "title": "TST guideline", "scope": {"process": "fdm"},
            "limits": [{"characteristic": "min_wall", "operator": ">=", "quantity": {"value": minimum, "units": "mm"},
                        "citations": [fx.source("datasheet", "TST guide")]}]}, sort_keys=False)

    def setUp(self) -> None:
        super().setUp()
        self.shipped = self.root / "shipped"
        guidelines = fx.intent_module()._sibling("cad_record_guidelines", "guidelines.py")
        patch = mock.patch.object(guidelines, "SHIPPED", self.shipped)
        patch.start()
        self.addCleanup(patch.stop)

    def refused_as_stale(self, hw: Path) -> None:
        result, report = self.release(hw)
        findings = report.get("findings", [])
        self.assertEqual((result, report["status"]), (1, "refused"), json.dumps(findings, indent=1))
        messages = [item["message"] for item in findings if item.get("code") == "release.acceptance"]
        self.assertTrue(any("stale" in message and "LMP-" in message for message in messages), messages)

    def test_editing_a_project_guideline_after_the_freeze_refuses_the_release(self) -> None:
        hw = self.project(before_build=lambda hw: write(hw / "manufacturing" / "guidelines" / "generic.yaml", self.guideline(0.8)))
        write(hw / "manufacturing" / "guidelines" / "generic.yaml", self.guideline(0.9))
        self.refused_as_stale(hw)

    def test_editing_a_shipped_guideline_after_the_freeze_refuses_the_release(self) -> None:
        write(self.shipped / "generic.yaml", self.guideline(0.8))
        hw = self.project(before_build=lambda hw: None)  # options force a fresh build, with the shipped set present
        write(self.shipped / "generic.yaml", self.guideline(0.9))
        self.refused_as_stale(hw)

    def test_the_same_flow_without_an_edit_releases(self) -> None:
        write(self.shipped / "generic.yaml", self.guideline(0.8))
        hw = self.project(before_build=lambda hw: write(hw / "manufacturing" / "guidelines" / "project.yaml",
                                                         self.guideline(0.8).replace("fdm.generic", "fdm.project")))
        result, report = self.release(hw)
        self.assertEqual((result, report["status"]), (0, "released"), json.dumps(report.get("findings"), indent=1))


if __name__ == "__main__":
    unittest.main()
