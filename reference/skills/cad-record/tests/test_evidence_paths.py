#!/usr/bin/env python3
"""evidence_paths.py and its acceptance points: evidence in the record cites files the record holds.

An accepted ledger entry whose structured paths or free text name scratch (`.cad-work/`, `hw/.cad/`), a
temp directory, the home directory or anything outside the project root, or a record result its artifacts
do not list, is refused at the assessment, in the validate ledger findings and in the acceptance inventory.
The fixture mirrors EV-002 and EV-003 of the small-mechanism bench fixture that cited its measurement
script and result under .cad-work/.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from modload import load_module as load  # noqa: E402

acceptance = load("cad_record_acceptance_fixtures", HERE / "fixtures" / "acceptance.py")
fx, mi, evidence, impact = acceptance.fx, acceptance.mi, acceptance.evidence, acceptance.impact
paths_module = load("cad_record_evidence_paths", HERE.parent / "scripts" / "evidence_paths.py")

TODAY = date(2026, 6, 1)
V1 = "a" * 64
SUBJECT = {"product": True, "requirements": ["REQ-001"]}
SIMULATION = "requirement.simulation_supported@REQ-001"
EVIDENCE_DIR = "hw/checks/v1/lever/evidence"
RESULT = f"{EVIDENCE_DIR}/regional-v1.json"
SCRIPT = f"{EVIDENCE_DIR}/regional_v1.py"
VETOED_METHOD = ("BRepExtrema distance from the sealed v1 lever STEP to each bracket STEP face, J-001 0 to 75 deg "
                 "(lead script .cad-work/layout/regional_v1.py, result .cad-work/layout/regional-v1.json): 0.300 mm.")


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True,
                   capture_output=True)


class Project(unittest.TestCase):
    """A git project with the TST record. Its hw/checks/v1/lever/evidence folder holds the promoted measurement."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-evidence-paths-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.hw = fx.write_record(self.root / "hw", fx.tst_record())
        (self.root / "notes").mkdir()
        (self.root / "notes" / "method.txt").write_text("tracked note\n", encoding="utf-8")
        (self.root / "notes" / "untracked.txt").write_text("untracked note\n", encoding="utf-8")
        (self.root / ".cad-work" / "layout").mkdir(parents=True)
        (self.root / ".cad-work" / "layout" / "regional_v1.py").write_text("print()\n", encoding="utf-8")
        (self.hw / ".cad").mkdir()
        (self.hw / ".cad" / "builds.json").write_text("{}\n", encoding="utf-8")
        evidence_dir = self.root / EVIDENCE_DIR
        evidence_dir.mkdir(parents=True)
        (self.root / RESULT).write_text('{"min_mm": 0.3}\n', encoding="utf-8")
        (self.root / SCRIPT).write_text("print()\n", encoding="utf-8")
        sealed = self.hw / "versions" / "v3"
        sealed.mkdir(parents=True)
        (sealed / "assembly.step").write_text("ISO-10303-21;\n", encoding="utf-8")
        (self.hw / "versions" / "v3.partial").mkdir()
        (self.hw / "versions" / "v3.partial" / "assembly.step").write_text("ISO-10303-21;\n", encoding="utf-8")
        git(self.root, "init", "-q")
        git(self.root, "add", "hw/product.yaml", "hw/verification.csv", "notes/method.txt")
        git(self.root, "add", "-f", "hw/.cad/builds.json")  # tracked on purpose: only the scratch rule may refuse it
        git(self.root, "commit", "-q", "-m", "fixture")
        self.record = impact.read_record(self.hw)
        self.paths = evidence.project_paths(self.hw)

    def entry(self, ident: str = "EV-001", *, artifacts: list[str] | None = None, **extra: Any) -> dict[str, Any]:
        return acceptance.entry(self.record, ident, SUBJECT, "simulation_supported", requirement="REQ-001", version="v1",
                                manifest_sha256=V1, artifacts=artifacts or ["hw/verification.csv"], hw=self.hw, **extra)

    def refusal(self, entry: dict[str, Any]) -> list[Any]:
        return paths_module.entry_problems(self.paths, entry)

    def assessed(self, entry: dict[str, Any]) -> Any:
        record = mi.normalize_record({**{rel: doc for rel, doc in fx.tst_record().items() if not rel.startswith("_")},
                                      "manufacturing/evidence.yaml": {"entries": [entry]}})
        return evidence.assess(record, version="v1", manifest_sha256=V1, today=TODAY, paths=self.paths,
                               approved=lambda decision: True)

    def points(self, entry: dict[str, Any]) -> tuple[set[str], set[str], bool]:
        """What the three acceptance points say about `entry`: the assessment's finding codes, the ledger
        findings codes and whether the acceptance inventory refuses."""
        assessed = {f.code for f in self.assessed(entry).findings}
        acceptance.write_ledger(self.hw, [entry])
        record = impact.read_record(self.hw)
        ledger = {f.code for f in evidence.ledger_findings(record, approved=lambda _: True, today=TODAY, paths=self.paths)}
        try:
            evidence.acceptance_inventory(self.hw, record)
        except evidence.EvidenceError:
            return assessed, ledger, True
        return assessed, ledger, False


class VetoedFixture(Project):
    def test_scratch_script_and_result_in_method_are_refused_naming_the_path(self) -> None:
        entry = self.entry(method=VETOED_METHOD)
        problems = self.refusal(entry)
        self.assertEqual({p.code for p in problems}, {"evidence.scratch_path"})
        message = " ".join(p.message for p in problems)
        self.assertIn(".cad-work/layout/regional_v1.py", message)
        self.assertIn(".cad-work/layout/regional-v1.json", message)
        self.assertIn("hw/checks", message)

    def test_the_assessment_refuses_the_entry_and_does_not_count_it(self) -> None:
        result = self.assessed(self.entry(method=VETOED_METHOD))
        finding = next(f for f in result.findings if f.code == "evidence.scratch_path")
        self.assertEqual(finding.severity, "error")
        self.assertIn(".cad-work/layout/regional_v1.py", finding.message)
        self.assertEqual(result.statuses[SIMULATION].result, "unknown")

    def test_the_same_entry_with_the_result_promoted_is_accepted(self) -> None:
        method = f"BRepExtrema distance, J-001 0 to 75 deg (lead script {SCRIPT}, result {RESULT}): 0.300 mm."
        entry = self.entry(method=method, artifacts=["hw/verification.csv", SCRIPT, RESULT])
        self.assertEqual(self.refusal(entry), [])
        result = self.assessed(entry)
        self.assertNotIn("evidence.scratch_path", {f.code for f in result.findings})
        self.assertNotIn("evidence.uncited_artifact", {f.code for f in result.findings})
        self.assertEqual(result.statuses[SIMULATION].result, "pass")

    def test_a_promoted_result_the_text_cites_but_the_artifacts_omit_is_refused(self) -> None:
        entry = self.entry(method=f"result {RESULT}: 0.300 mm")
        problems = self.refusal(entry)
        self.assertEqual([p.code for p in problems], ["evidence.uncited_artifact"])
        self.assertIn(RESULT, problems[0].message)


class OutsideTheRecord(Project):
    def test_each_location_outside_the_record_is_refused(self) -> None:
        cases = {
            "dotdot escape": "see ../outside/result.json",
            "absolute outside": "see /etc/hosts.json",
            "home": "see ~/measurements/result.csv",
            "tmp": "see /tmp/result.json",
            "var folders": "see /var/folders/ab/cd/result.json",
            "hw/.cad scratch": "see hw/.cad/builds.json",
            "dotdot into scratch": "see hw/../.cad-work/layout/regional_v1.py",
            "untracked file in a git project": "see notes/untracked.txt",
            "unsealed version": "see hw/versions/v3.partial/assembly.step",
            "missing file": "see notes/absent.txt",
        }
        for name, method in cases.items():
            with self.subTest(name):
                problems = self.refusal(self.entry(method=method))
                self.assertEqual([p.code for p in problems], ["evidence.scratch_path"], method)
                self.assertIn(method.split()[-1], problems[0].message)

    def test_a_structured_artifact_in_scratch_is_refused(self) -> None:
        entry = self.entry(artifacts=["hw/verification.csv"])
        entry["artifacts"].append({"path": "hw/.cad/builds.json", "sha256": "0" * 64})
        problems = self.refusal(entry)
        self.assertEqual([p.code for p in problems], ["evidence.scratch_path"])
        self.assertIn("hw/.cad/builds.json", problems[0].message)

    def test_every_prose_field_is_scanned(self) -> None:
        for field in ("tool", "producer", "note", "coverage", "uncertainty"):
            with self.subTest(field):
                problems = self.refusal(self.entry(**{field: "run .cad-work/layout/regional_v1.py"}))
                self.assertEqual([p.code for p in problems], ["evidence.scratch_path"])
                self.assertEqual(problems[0].where, field)

    def test_a_disposition_reason_is_scanned(self) -> None:
        disposition = {"finding": "f1", "status": "declined", "decision": "DR-001",
                       "producer": {"bundle": "hw/checks/v1/lever", "manifest_sha256": V1},
                       "reason": "declined, see /tmp/review.txt"}
        problems = paths_module.disposition_problems(self.paths, disposition)
        self.assertEqual([p.code for p in problems], ["evidence.scratch_path"])


class NotAPath(Project):
    def test_prose_that_is_not_a_path_passes(self) -> None:
        for prose in ("Fit is ~5 mm", "thread 1/4-20 UNC", "screw M6x20", "tolerance ±0.1/0.2", "load 5 N/mm2.",
                      "speed 10 mm/s", "pass/fail", "ratio 3/8 in", "see https://example.com/datasheet.pdf",
                      "rev 1.2/1.3", "ISO 286-1 and/or ANSI B4.1", "sealed v3 (full-sweep)", "ratio 3/4",
                      "dated 2026/11/17", "tag v1.2", "range 1.5/2.0", "layers 0.1mm/0.2mm", "pitch 2x3.5mm/4mm",
                      "+0.2mm/\u22120.1mm", "\u00b10.1mm/\u00b10.2mm", "+0.2mm/-0.1mm", "M6x20/A2", "PLA/PETG",
                      "TPU 95A/98A", "0.4mm/0.6mm nozzle", "ISO 4762 M5x12"):
            with self.subTest(prose):
                self.assertEqual(self.refusal(self.entry(method=prose)), [], prose)

    def test_a_tracked_in_tree_path_passes(self) -> None:
        self.assertEqual(self.refusal(self.entry(method="rationale in notes/method.txt:3.")), [])

    def test_a_sealed_version_path_the_entry_lists_passes(self) -> None:
        entry = self.entry(method="read back hw/versions/v3/assembly.step", artifacts=["hw/versions/v3/assembly.step"])
        self.assertEqual(self.refusal(entry), [])

    def test_a_sealed_version_path_the_entry_does_not_list_is_uncited(self) -> None:
        problems = self.refusal(self.entry(method="read back hw/versions/v3/assembly.step"))
        self.assertEqual([p.code for p in problems], ["evidence.uncited_artifact"])

class DependentEvidence(Project):
    """EV-004 and EV-005 of the bench fixture rest on "EV-003 method", so a refused EV-003 must not leave them accepted."""

    def results(self, entries: list[dict[str, Any]]) -> tuple[dict[str, str], list[Any]]:
        record = mi.normalize_record({**{rel: doc for rel, doc in fx.tst_record().items() if not rel.startswith("_")},
                                      "manufacturing/evidence.yaml": {"entries": entries}})
        rows = evidence._rows(self.hw / "verification.csv")
        result = evidence.assess(record, version="v1", manifest_sha256=V1, today=TODAY, paths=self.paths,
                                 approved=lambda decision: True, verification=rows)
        shown = {e["id"]: e["result"] for row in result.verification for e in row["evidence"]}
        return shown, [f for f in result.findings if f.code == "evidence.refused_dependency"]

    def chain(self) -> list[dict[str, Any]]:
        return [self.entry("EV-002", method=VETOED_METHOD), self.entry("EV-003", method=VETOED_METHOD),
                self.entry("EV-004", method="Full sweep clear. The per-face measurement (EV-003 method) gives 0.000 mm."),
                self.entry("EV-005", method="Same measurement as EV-003; minimum clearance is 2.000 mm.")]

    def test_entries_that_rest_on_a_refused_entry_are_unknown_and_name_it(self) -> None:
        shown, found = self.results(self.chain())
        self.assertEqual(shown, {"EV-002": "unknown", "EV-003": "unknown", "EV-004": "unknown", "EV-005": "unknown"})
        self.assertEqual({f.path.rsplit("/", 1)[1]: f.message for f in found}.keys(), {"EV-004", "EV-005"})
        for finding in found:
            self.assertEqual(finding.severity, "error")
            self.assertIn("EV-003", finding.message)

    def test_the_dependency_is_transitive(self) -> None:
        entries = self.chain() + [self.entry("EV-006", method="Margin follows from EV-005.")]
        shown, found = self.results(entries)
        self.assertEqual(shown["EV-006"], "unknown")
        self.assertIn("EV-005", next(f.message for f in found if f.path.endswith("EV-006")))

    def test_an_entry_that_rests_on_an_accepted_entry_stays_accepted(self) -> None:
        entries = [self.entry("EV-002"), self.entry("EV-003", method="Same measurement as EV-002.")]
        shown, found = self.results(entries)
        self.assertEqual(shown, {"EV-002": "pass", "EV-003": "pass"})
        self.assertEqual(found, [])

    def test_a_cycle_between_accepted_entries_stays_accepted_and_one_refused_member_taints_the_other(self) -> None:
        shown, _ = self.results([self.entry("EV-002", method="see EV-003"), self.entry("EV-003", method="see EV-002")])
        self.assertEqual(shown, {"EV-002": "pass", "EV-003": "pass"})
        shown, _ = self.results([self.entry("EV-002", method="see EV-003"),
                                 self.entry("EV-003", method="see EV-002 and .cad-work/x.json")])
        self.assertEqual(shown, {"EV-002": "unknown", "EV-003": "unknown"})

    def test_the_ledger_findings_report_the_dependents(self) -> None:
        acceptance.write_ledger(self.hw, self.chain())
        findings = evidence.ledger_findings(impact.read_record(self.hw), approved=lambda _: True, today=TODAY,
                                            paths=self.paths)
        self.assertEqual({f.path.rsplit("/", 1)[1] for f in findings if f.code == "evidence.refused_dependency"},
                         {"EV-004", "EV-005"})

    def test_the_acceptance_inventory_refuses_the_dependents(self) -> None:
        acceptance.write_ledger(self.hw, [self.entry("EV-003", method=VETOED_METHOD),
                                          self.entry("EV-004", method="Same measurement as EV-003.")])
        with self.assertRaisesRegex(evidence.EvidenceError, "EV-004.*EV-003"):
            evidence.acceptance_inventory(self.hw, impact.read_record(self.hw))

    def test_a_refused_evidence_id_in_physical_configuration_makes_the_entry_unknown(self) -> None:
        entries = [self.entry("EV-003", method=VETOED_METHOD),
                   self.entry("EV-004", physical={**acceptance.PHYSICAL, "configuration": "as measured in EV-003"})]
        shown, found = self.results(entries)
        self.assertEqual(shown, {"EV-003": "unknown", "EV-004": "unknown"})
        self.assertIn("EV-003", found[0].message)

    def test_the_scratch_physical_configuration_is_refused_at_all_three_acceptance_points(self) -> None:
        entry = self.entry(physical={**acceptance.PHYSICAL, "configuration": "see .cad-work/x.json"})
        shown, _ = self.results([entry])
        self.assertEqual(shown, {"EV-001": "unknown"})
        acceptance.write_ledger(self.hw, [entry])
        record = impact.read_record(self.hw)
        found = evidence.ledger_findings(record, approved=lambda _: True, today=TODAY, paths=self.paths)
        self.assertEqual({f.code for f in found}, {"evidence.scratch_path"})
        with self.assertRaisesRegex(evidence.EvidenceError, r"\.cad-work/x\.json"):
            evidence.acceptance_inventory(self.hw, record)


class Extensions(Project):
    def test_alphanumeric_extensions_are_scanned(self) -> None:
        sealed = self.hw / "versions" / "v3" / "manufacturing" / "TST-0001"
        sealed.mkdir(parents=True)
        (sealed / "part.3mf").write_bytes(b"3mf")
        (self.root / "notes" / "untracked.3mf").write_bytes(b"3mf")
        cases = {
            "missing 3mf": ("see manufacturing/TST-0001/part.3mf", "evidence.scratch_path"),
            "untracked 3mf": ("see notes/untracked.3mf", "evidence.scratch_path"),
            "uncited sealed 3mf": ("see hw/versions/v3/manufacturing/TST-0001/part.3mf", "evidence.uncited_artifact"),
            "missing mp4": ("see results/run.mp4", "evidence.scratch_path"),
            "missing h5": ("see data/out.h5", "evidence.scratch_path"),
            "scratch 3mf": ("see .cad-work/part.3mf", "evidence.scratch_path"),
        }
        for name, (method, code) in cases.items():
            with self.subTest(name):
                self.assertEqual([p.code for p in self.refusal(self.entry(method=method))], [code], method)

    def test_a_listed_sealed_3mf_or_parquet_is_accepted(self) -> None:
        sealed = self.hw / "versions" / "v3" / "manufacturing" / "TST-0001"
        sealed.mkdir(parents=True)
        for name in ("part.3mf", "samples.parquet"):
            (sealed / name).write_bytes(b"x")
            path = f"hw/versions/v3/manufacturing/TST-0001/{name}"
            self.assertEqual(self.refusal(self.entry(method=f"read back {path}", artifacts=[path])), [], name)


class NestedProse(Project):
    """Nested prose fields, such as physical.configuration, get the same scan as top-level text."""

    def physical(self, text: str) -> dict[str, Any]:
        return {"physical": {**acceptance.PHYSICAL, "configuration": text}}

    def test_scratch_geometry_in_physical_configuration_is_refused(self) -> None:
        problems = self.refusal(self.entry(**self.physical("as built from .cad-work/layout/regional_v1.py")))
        self.assertEqual([p.code for p in problems], ["evidence.scratch_path"])
        self.assertEqual(problems[0].where, "physical.configuration")

    def test_the_structured_configuration_object_is_not_prose(self) -> None:
        self.assertEqual(self.refusal(self.entry()), [])

    def test_the_other_prose_fields_below_nested_objects_are_scanned(self) -> None:
        for where, extra in {"criterion.conditions": {"criterion": {"conditions": "see /tmp/x.json"}},
                             "criterion.source.reference": {"criterion": {"source": {"reference": "see /tmp/x.json"}}},
                             "waiver.reason": {"waiver": {"reason": "see /tmp/x.json"}},
                             "source.origin": {"source": {"origin": "see /tmp/x.json"}}}.items():
            with self.subTest(where):
                entry = self.entry()
                for key, value in extra.items():
                    entry[key] = {**entry.get(key, {}), **value}
                self.assertEqual([p.where for p in self.refusal(entry)], [where])

    def test_a_scratch_criterion_source_artifact_is_refused(self) -> None:
        entry = self.entry()
        entry["criterion"] = {**entry["criterion"], "source": {"kind": "test", "reference": "TST",
                                                              "artifact": "../../outside.pdf", "sha256": "0" * 64}}
        self.assertEqual([p.where for p in self.refusal(entry)], ["criterion.source.artifact"])

    def test_a_scratch_producer_bundle_of_a_disposition_is_refused(self) -> None:
        disposition = {"finding": "f1", "status": "declined", "decision": "DR-001", "reason": "TST",
                       "producer": {"bundle": "hw/.cad/bundle", "manifest_sha256": V1}}
        self.assertEqual([p.where for p in paths_module.disposition_problems(self.paths, disposition)],
                         ["producer.bundle"])


class Symlinks(Project):
    """A tracked symlink that prose cites counts as the file it resolves to, not as its own name."""

    def setUp(self) -> None:
        super().setUp()
        self.outside = tempfile.TemporaryDirectory(prefix="cad-evidence-outside-")
        self.addCleanup(self.outside.cleanup)
        target = Path(self.outside.name) / "result.txt"
        target.write_text("outside\n", encoding="utf-8")
        notes = self.root / "notes"
        (notes / "to_outside.txt").symlink_to(target)
        (notes / "to_scratch.txt").symlink_to("../.cad-work/layout/regional_v1.py")
        (notes / "to_hw_cad.txt").symlink_to("../hw/.cad/builds.json")
        (notes / "to_tracked.txt").symlink_to("method.txt")
        git(self.root, "add", "notes/to_outside.txt", "notes/to_scratch.txt", "notes/to_hw_cad.txt", "notes/to_tracked.txt")
        git(self.root, "commit", "-q", "-m", "links")
        self.paths = evidence.project_paths(self.hw)

    def test_tracked_links_that_resolve_outside_or_into_scratch_are_refused_at_all_three_points(self) -> None:
        for name in ("to_outside", "to_scratch", "to_hw_cad"):
            with self.subTest(name):
                entry = self.entry(method=f"see notes/{name}.txt")
                self.assertEqual([p.code for p in self.refusal(entry)], ["evidence.scratch_path"])
                assessed, ledger, inventory = self.points(entry)
                self.assertEqual((assessed & {"evidence.scratch_path"}, ledger, inventory),
                                 ({"evidence.scratch_path"}, {"evidence.scratch_path"}, True))

    def test_a_tracked_link_to_a_tracked_file_in_the_root_passes_at_all_three_points(self) -> None:
        entry = self.entry(method="rationale in notes/to_tracked.txt:3")
        self.assertEqual(self.refusal(entry), [])
        self.assertEqual(self.points(entry), (set(), set(), False))


class Formats(Project):
    # Any 1 to 8 character alphanumeric extension with a letter, after a stem that is not a number.
    EXTENSIONS = (".3mf", ".3MF", ".3ds", ".3dm", ".3gp", ".7z", ".7Z", ".4dv", ".2bk", ".bgcode", ".sqlite", ".parquet")

    def test_formats_in_an_unlisted_result_folder_are_refused_in_any_case(self) -> None:
        for extension in self.EXTENSIONS:
            with self.subTest(extension):
                name = f"{EVIDENCE_DIR}/run{extension}"
                (self.root / name).write_bytes(b"x")
                problems = self.refusal(self.entry(method=f"see {name}"))
                self.assertEqual([p.code for p in problems], ["evidence.uncited_artifact"], name)
                self.assertEqual(self.refusal(self.entry(method=f"see {name}", artifacts=[name])), [], name)

    def test_a_missing_format_is_refused(self) -> None:
        for extension in self.EXTENSIONS:
            with self.subTest(extension):
                problems = self.refusal(self.entry(method=f"see results/absent{extension}"))
                self.assertEqual([p.code for p in problems], ["evidence.scratch_path"])

    def test_numeric_prose_with_a_unit_suffix_is_no_format(self) -> None:
        for prose in ("layers 0.1mm/0.2mm", "gap 0.3mm/0.7zones", "range 1.5/2.0", "pitch 2x3.5mm/4mm", "tag v1.2/v1.3",
                      "step 2.0mm/12.5mm", "min -0.5mm/+0.5mm", "width 0.2mm", "tag v1.2/v1.3.4"):
            with self.subTest(prose):
                self.assertEqual(self.refusal(self.entry(method=prose)), [], prose)


class FileUrls(Project):
    def test_a_file_url_with_an_anchor_or_line_suffix_to_a_tracked_file_passes_at_all_three_points(self) -> None:
        url = (self.root / "notes" / "method.txt").as_uri()
        for suffix in ("", "#L3", ":3", ":3:7", "#anchor"):
            with self.subTest(suffix):
                entry = self.entry(method=f"rationale in {url}{suffix}.")
                self.assertEqual(self.refusal(entry), [])
                self.assertEqual(self.points(entry), (set(), set(), False))

    def test_a_file_url_with_an_anchor_to_scratch_is_still_refused(self) -> None:
        url = (self.root / ".cad-work" / "layout" / "regional_v1.py").as_uri()
        self.assertEqual([p.code for p in self.refusal(self.entry(method=f"see {url}#L9"))], ["evidence.scratch_path"])


class SchemaLeaves:
    """The leaf fields below one schema definition, each typed as prose ($defs/text) or not."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.documents: dict[str, Any] = {}
        self.found: dict[str, bool] = {}

    def resolve(self, ref: str, file: str) -> tuple[Any, str]:
        target, _, pointer = ref.partition("#")
        file = target or file
        node = self.documents.setdefault(file, json.loads((self.directory / file).read_text(encoding="utf-8")))
        for part in [x for x in pointer.split("/") if x]:
            node = node[part]
        return node, file

    def collect(self, file: str, definition: str) -> dict[str, bool]:
        node, file = self.resolve(f"#{definition}", file)
        self.walk(node, file, "")
        return self.found

    def walk(self, node: Any, file: str, pointer: str) -> None:
        if not isinstance(node, dict):
            self.found.setdefault(pointer, False)
            return
        while "$ref" in node:
            if node["$ref"].endswith("$defs/text"):
                self.found[pointer] = True
                return
            node, file = self.resolve(node["$ref"], file)
        for key in ("oneOf", "anyOf", "allOf"):
            for part in node.get(key, []):
                self.walk(part, file, pointer)
        self.members(node, file, pointer)

    def members(self, node: dict[str, Any], file: str, pointer: str) -> None:
        extra = node.get("additionalProperties")
        if "properties" in node or isinstance(extra, dict):
            for field, part in node.get("properties", {}).items():
                self.walk(part, file, f"{pointer}.{field}" if pointer else field)
            if isinstance(extra, dict):
                self.walk(extra, file, f"{pointer}.*" if pointer else "*")
        elif node.get("type") == "array" and "items" in node:
            self.walk(node["items"], file, pointer + "[]")
        elif node.get("type") == "string" or any(key in node for key in ("enum", "const", "pattern")):
            self.found.setdefault(pointer, False)


class SchemaTie(unittest.TestCase):
    """The skipped pointers match the non-prose fields of the ledger schemas, so a schema change that adds or retypes one fails here."""

    SCHEMAS = HERE.parent / "schemas"

    def leaves(self, name: str, definition: str) -> dict[str, bool]:
        return SchemaLeaves(self.SCHEMAS).collect(name, definition)

    def covered(self, skipped: frozenset[str], pointer: str) -> bool:
        return any(pointer == s or pointer.startswith((s + ".", s + "[]")) for s in skipped)

    def check(self, file: str, definition: str, skipped: frozenset[str]) -> None:
        leaves = self.leaves(file, definition)
        prose = {p for p, is_text in leaves.items() if is_text}
        structured = {p for p, is_text in leaves.items() if not is_text}
        self.assertEqual({p for p in prose if self.covered(skipped, p)}, set(), "a prose field is skipped")
        self.assertEqual({p for p in structured if not self.covered(skipped, p)}, set(), "a structured field is scanned")
        self.assertEqual({s for s in skipped if not any(self.covered(frozenset({s}), p) for p in structured)}, set(),
                         "a skipped pointer matches no structured field of the schema")

    def test_the_entry_exclusions_match_the_evidence_schema(self) -> None:
        self.check("manufacturing-evidence.schema.json", "/$defs/entry", paths_module.ENTRY_STRUCTURED)

    def test_the_disposition_exclusions_match_the_findings_schema(self) -> None:
        self.check("manufacturing-findings.schema.json", "/$defs/disposition", paths_module.DISPOSITION_STRUCTURED)


class ScratchStore(Project):
    """Store objects under hw/.cad have no extension, so only the directory marks them as scratch."""

    def setUp(self) -> None:
        super().setUp()
        self.sha = "ab" * 32
        store = self.hw / ".cad" / "parts"
        store.mkdir(parents=True)
        (store / self.sha).write_bytes(b"store object")
        git(self.root, "add", "-f", f"hw/.cad/parts/{self.sha}")  # tracked on purpose: only the scratch rule may refuse it
        git(self.root, "commit", "-q", "-m", "store object")
        self.paths = evidence.project_paths(self.hw)

    def test_an_extensionless_store_object_is_refused_in_each_spelling(self) -> None:
        for spelling in (f"hw/.cad/parts/{self.sha}", f".cad/parts/{self.sha}", f"./hw/.cad/parts/{self.sha}",
                         str(self.hw / ".cad" / "parts" / self.sha), "hw/.cad"):
            with self.subTest(spelling):
                problems = self.refusal(self.entry(method=f"built from {spelling}."))
                self.assertEqual([p.code for p in problems], ["evidence.scratch_path"], spelling)

    def test_an_extensionless_store_object_is_refused_at_all_three_points(self) -> None:
        entry = self.entry(method=f"geometry in hw/.cad/parts/{self.sha}")
        assessed, ledger, inventory = self.points(entry)
        self.assertEqual((assessed & {"evidence.scratch_path"}, ledger, inventory),
                         ({"evidence.scratch_path"}, {"evidence.scratch_path"}, True))

    def test_an_entry_that_rests_on_the_refused_store_entry_is_unknown(self) -> None:
        record = mi.normalize_record({**{rel: doc for rel, doc in fx.tst_record().items() if not rel.startswith("_")},
                                      "manufacturing/evidence.yaml": {"entries": [
                                          self.entry("EV-003", method=f"geometry in hw/.cad/parts/{self.sha}"),
                                          self.entry("EV-004", method="Same measurement as EV-003.")]}})
        rows = evidence._rows(self.hw / "verification.csv")
        result = evidence.assess(record, version="v1", manifest_sha256=V1, today=TODAY, paths=self.paths,
                                 approved=lambda decision: True, verification=rows)
        shown = {e["id"]: e["result"] for row in result.verification for e in row["evidence"]}
        self.assertEqual(shown, {"EV-003": "unknown", "EV-004": "unknown"})


class DotSlashNames(Project):
    """A leading ./ is no path shape of its own: ./measurement.json is a file name that the rule must judge."""

    def test_a_missing_or_untracked_dot_slash_file_is_refused_at_all_three_points(self) -> None:
        for state in ("missing", "untracked"):
            with self.subTest(state):
                if state == "untracked":
                    (self.root / "measurement.json").write_text("{}\n", encoding="utf-8")
                entry = self.entry(method="result in ./measurement.json")
                self.assertEqual([p.code for p in self.refusal(entry)], ["evidence.scratch_path"])
                assessed, ledger, inventory = self.points(entry)
                self.assertEqual((assessed & {"evidence.scratch_path"}, ledger, inventory),
                                 ({"evidence.scratch_path"}, {"evidence.scratch_path"}, True))

    def test_other_dot_slash_names_are_judged_and_numbers_are_not(self) -> None:
        for name in ("./out.3mf", "./a.7z", "./notes/untracked.txt"):
            with self.subTest(name):
                self.assertEqual([p.code for p in self.refusal(self.entry(method=f"see {name}"))],
                                 ["evidence.scratch_path"])
        self.assertEqual(self.refusal(self.entry(method="width ./0.2mm")), [])
        self.assertEqual(self.refusal(self.entry(method="rationale in ./notes/method.txt")), [])


class FiguresWithoutAPath(Project):
    """What the rule cannot see: figures that come from a result the text never names."""

    def test_measured_figures_with_no_path_in_the_text_raise_no_finding(self) -> None:
        entry = self.entry(method="Minimum clearance 2.000 mm over 0 to 75 deg, measured on the sealed STEP.",
                           artifacts=["hw/versions/v3/assembly.step"])
        self.assertEqual(self.refusal(entry), [])


class AcceptancePoints(Project):
    def test_the_acceptance_inventory_refuses_scratch_text(self) -> None:
        acceptance.write_ledger(self.hw, [self.entry(method=VETOED_METHOD)])
        with self.assertRaisesRegex(evidence.EvidenceError, r"\.cad-work/layout/regional_v1\.py"):
            evidence.acceptance_inventory(self.hw, impact.read_record(self.hw))

    def test_the_acceptance_inventory_accepts_the_promoted_entry(self) -> None:
        method = f"script {SCRIPT}, result {RESULT}"
        acceptance.write_ledger(self.hw, [self.entry(method=method, artifacts=[SCRIPT, RESULT])])
        inventory = evidence.acceptance_inventory(self.hw, impact.read_record(self.hw))
        self.assertIn(RESULT, inventory)

    def test_the_ledger_findings_report_scratch_text_as_errors(self) -> None:
        acceptance.write_ledger(self.hw, [self.entry(method=VETOED_METHOD)])
        findings = evidence.ledger_findings(impact.read_record(self.hw), approved=lambda _: True, today=TODAY,
                                            paths=self.paths)
        self.assertEqual({f.code for f in findings}, {"evidence.scratch_path"})
        self.assertEqual({f.severity for f in findings}, {"error"})


class OutsideGit(unittest.TestCase):
    def test_a_project_that_is_no_git_work_tree_still_refuses_scratch_and_outside(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cad-evidence-paths-") as name:
            root = Path(name).resolve()
            (root / "hw").mkdir()
            (root / "notes").mkdir()
            (root / "notes" / "a.txt").write_text("a\n", encoding="utf-8")
            paths = evidence.project_paths(root / "hw")
            self.assertIsNone(paths.tracked)
            self.assertIsNone(paths.judge("notes/a.txt").problem)
            self.assertIsNotNone(paths.judge(".cad-work/x.json").problem)
            self.assertIsNotNone(paths.judge("../x.json").problem)


if __name__ == "__main__":
    unittest.main()
