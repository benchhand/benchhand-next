#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""decision_records.py: the MADR 4.0.0 writer, the reader and the generated index.

Tests are unittest classes so the repo's shard runner (scripts/ci_shards.py) collects them; pytest runs
them too."""

from __future__ import annotations

import datetime
import string
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml
from hypothesis import example, given
from hypothesis import strategies as st

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL.parents[1] / "scripts"))
import property_profile  # noqa: E402,F401  (registers and loads the profile)
from modload import load_module  # noqa: E402

dr = load_module("cad_record_decision_records", SKILL / "scripts" / "decision_records.py")

DAY = datetime.date(2026, 10, 26)
FULL: dict[str, Any] = {
    "title": "Press-fit pivot pins",
    "status": "accepted",
    "date": DAY,
    "decision_makers": ("Sjors", "Ana"),
    "consulted": ("Machinist",),
    "informed": ("Reviewer",),
    "context": "Each pin has clearance to every part.\n\nThe connection check needs contact.",
    "drivers": ("Fixed joints must touch", "Pins are easy to fit"),
    "options": ("Clearance fit", "Press fit"),
    "chosen": "Press fit",
    "justification": "it closes the gap at fixed joints",
    "consequences": "Pins are made to drawing.",
    "confirmation": "`cad_model.py check` passes.",
    "pros_and_cons": "### Press fit\n\n* Good, because it touches.",
    "more_information": "See DR-004.",
}
MINIMAL: dict[str, Any] = {
    "title": "Use aluminium",
    "status": "proposed",
    "date": DAY,
    "context": "Need a metal.",
    "options": ("Aluminium",),
    "chosen": "Aluminium",
    "justification": "it is light",
}


def document(front: str | None = None, body: str | None = None) -> str:
    front = front if front is not None else "status: accepted\ndate: 2026-10-26\ndecision-makers:\n  - Sjors\n"
    body = body if body is not None else (
        "# Title\n\n## Context and Problem Statement\n\nWhy.\n\n## Considered Options\n\n* A\n* B\n\n"
        '## Decision Outcome\n\nChosen option: "A", because it is better.\n')
    return f"---\n{front}---\n\n{body}"


class Base(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def put(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path


class WriteTests(Base):
    def test_the_first_record_is_numbered_one_and_named_after_its_title(self) -> None:
        path = dr.write_decision(self.dir, **FULL)
        self.assertEqual(path, self.dir / "DR-001-press-fit-pivot-pins.md")
        self.assertTrue(path.is_file())

    def test_front_matter_carries_the_madr_fields_by_their_madr_names(self) -> None:
        path = dr.write_decision(self.dir, **FULL)
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        front = yaml.safe_load(text.split("---\n")[1])
        self.assertEqual(front, {"status": "accepted", "date": DAY, "decision-makers": ["Sjors", "Ana"],
                                 "consulted": ["Machinist"], "informed": ["Reviewer"]})

    def test_the_body_follows_the_madr_template(self) -> None:
        text = dr.write_decision(self.dir, **FULL).read_text(encoding="utf-8")
        body = text.split("---\n", 2)[2]
        headings = [line for line in body.splitlines() if line.startswith("#")]
        self.assertEqual(headings, [
            "# Press-fit pivot pins", "## Context and Problem Statement", "## Decision Drivers",
            "## Considered Options", "## Decision Outcome", "### Consequences", "### Confirmation",
            "## Pros and Cons of the Options", "### Press fit", "## More Information"])
        self.assertIn('Chosen option: "Press fit", because it closes the gap at fixed joints.', body)

    def test_optional_front_matter_and_sections_are_left_out_when_empty(self) -> None:
        text = dr.write_decision(self.dir, **MINIMAL).read_text(encoding="utf-8")
        self.assertEqual(set(yaml.safe_load(text.split("---\n")[1])), {"status", "date"})
        for heading in ("Decision Drivers", "Consequences", "Confirmation", "More Information"):
            self.assertNotIn(heading, text)

    def test_numbers_continue_after_the_highest_existing_record(self) -> None:
        dr.write_decision(self.dir, **MINIMAL)
        second = dr.write_decision(self.dir, **{**MINIMAL, "title": "Use steel", "chosen": "Aluminium"})
        self.assertEqual(second.name, "DR-002-use-steel.md")

    def test_an_explicit_number_that_is_taken_is_refused_and_the_record_stays(self) -> None:
        first = dr.write_decision(self.dir, **MINIMAL)
        before = first.read_text(encoding="utf-8")
        with self.assertRaisesRegex(dr.DecisionRecordError, "DR-001"):
            dr.write_decision(self.dir, number=1, **{**MINIMAL, "title": "Other"})
        self.assertEqual(first.read_text(encoding="utf-8"), before)

    def test_writing_creates_a_missing_directory(self) -> None:
        path = dr.write_decision(self.dir / "hw" / "decisions", **MINIMAL)
        self.assertTrue(path.is_file())

    def test_the_chosen_option_must_be_one_of_the_options(self) -> None:
        with self.assertRaisesRegex(dr.DecisionRecordError, "chosen"):
            dr.write_decision(self.dir, **{**MINIMAL, "chosen": "Steel"})
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_invalid_input_is_refused_before_anything_is_written(self) -> None:
        cases = {
            "status": {"status": "approved-ish"},
            "date": {"date": "2026-10-26"},
            "title": {"title": "  "},
            "title without ASCII letters": {"title": "\u4e2d\u6587"},
            "context": {"context": ""},
            "options": {"options": ()},
            "multi-line option": {"options": ("A\nB",), "chosen": "A\nB"},
            "heading in prose": {"context": "ok\n## Considered Options\nforged"},
        }
        for label, change in cases.items():
            with self.subTest(label), self.assertRaises(dr.DecisionRecordError):
                dr.write_decision(self.dir, **{**MINIMAL, **change})
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_superseded_is_derived_from_superseded_by_and_never_stored_as_a_status(self) -> None:
        with self.assertRaisesRegex(dr.DecisionRecordError, "status"):
            dr.write_decision(self.dir, **{**MINIMAL, "status": "superseded by DR-004"})
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_superseded_by_is_written_as_a_front_matter_list(self) -> None:
        dr.write_decision(self.dir, **MINIMAL)
        path = dr.write_decision(self.dir, **{**MINIMAL, "title": "Old", "superseded_by": ("DR-001",)})
        front = yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1])
        self.assertEqual(front["superseded-by"], ["DR-001"])
        self.assertEqual(dr.read_decision(path).superseded_by, ("DR-001",))

    def test_superseded_by_must_name_an_existing_other_record(self) -> None:
        dr.write_decision(self.dir, **MINIMAL)
        for label, names in (("absent", ("DR-009",)), ("malformed", ("DR-9",)), ("itself", ("DR-002",)),
                             ("twice", ("DR-001", "DR-001"))):
            with self.subTest(label), self.assertRaises(dr.DecisionRecordError):
                dr.write_decision(self.dir, **{**MINIMAL, "title": "Old", "superseded_by": names})
        self.assertEqual(len(list(self.dir.glob("DR-*.md"))), 1)

    def test_gate_is_written_as_a_front_matter_mapping_and_read_back(self) -> None:
        path = dr.write_decision(self.dir, **MINIMAL, gate=("layout", "parts"))
        front = yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1])
        self.assertEqual(front["gate"], {"from": "layout", "to": "parts"})
        self.assertEqual(dr.read_decision(path).gate, ("layout", "parts"))

    def test_a_record_without_a_gate_reads_none_and_writes_no_key(self) -> None:
        path = dr.write_decision(self.dir, **MINIMAL)
        self.assertNotIn("gate", yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1]))
        self.assertIsNone(dr.read_decision(path).gate)

    def test_a_malformed_gate_is_refused_naming_the_file_and_the_key(self) -> None:
        for label, value in (("a scalar", "layout"), ("a list", "[layout, parts]"), ("without to", "{from: layout}"),
                             ("an unknown stage", "{from: layout, to: nowhere}"),
                             ("an extra key", "{from: layout, to: parts, via: x}"),
                             ("a number", "{from: 3, to: parts}"), ("a null", "null"),
                             ("equal ends", "{from: layout, to: layout}")):
            path = self.put("DR-001-gate.md", document(f"status: accepted\ndate: 2026-10-26\ngate: {value}\n"))
            with self.subTest(label), self.assertRaisesRegex(dr.DecisionRecordError, r"DR-001-gate\.md.*gate"):
                dr.read_decision(path)

    def test_writing_a_gate_with_an_unknown_stage_is_refused_and_leaves_the_directory(self) -> None:
        for gate in (("layout", "nowhere"), ("nowhere", "parts"), ("layout", "layout")):
            with self.subTest(gate), self.assertRaisesRegex(dr.DecisionRecordError, "gate"):
                dr.write_decision(self.dir, **MINIMAL, gate=gate)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_a_fenced_heading_in_prose_is_allowed(self) -> None:
        context = "Layout:\n\n```\n## not a heading\n```"
        path = dr.write_decision(self.dir, **{**MINIMAL, "context": context})
        self.assertEqual(dr.read_decision(path).context, context)


class ReadTests(Base):
    def test_a_written_record_reads_back_equal_to_its_input(self) -> None:
        path = dr.write_decision(self.dir, **FULL)
        record = dr.read_decision(path)
        self.assertEqual((record.number, record.slug), (1, "press-fit-pivot-pins"))
        self.assertEqual(record.id, "DR-001")
        for key, value in FULL.items():
            self.assertEqual(getattr(record, key), value, key)

    def test_read_decisions_returns_every_record_in_number_order(self) -> None:
        self.put("DR-010-b.md", document())
        self.put("DR-002-a.md", document())
        self.assertEqual([r.number for r in dr.read_decisions(self.dir)], [2, 10])

    def test_the_index_is_not_read_as_a_record(self) -> None:
        dr.write_decision(self.dir, **MINIMAL)
        self.assertEqual(len(dr.read_decisions(self.dir)), 1)

    def test_a_missing_directory_is_an_error(self) -> None:
        with self.assertRaises(dr.DecisionRecordError):
            dr.read_decisions(self.dir / "absent")

    def test_an_empty_directory_has_no_records(self) -> None:
        self.assertEqual(dr.read_decisions(self.dir), [])

    def test_malformed_input_is_refused_with_the_file_named(self) -> None:
        good_body = document().split("---\n", 2)[2]
        cases = {
            "no front matter": "# Title\n",
            "unterminated front matter": "---\nstatus: accepted\n",
            "invalid yaml": document("status: [accepted\n"),
            "front matter not a mapping": document("- a\n- b\n"),
            "missing status": document("date: 2026-10-26\ndecision-makers: [A]\n"),
            "missing date": document("status: accepted\ndecision-makers: [A]\n"),
            "unknown status": document("status: maybe\ndate: 2026-10-26\ndecision-makers: [A]\n"),
            "date as text": document("status: accepted\ndate: 'soon'\ndecision-makers: [A]\n"),
            "decision-makers a string": document("status: accepted\ndate: 2026-10-26\ndecision-makers: A\n"),
            "unknown key": document("status: accepted\ndate: 2026-10-26\ndecision-makers: [A]\nowner: x\n"),
            "no title": document(body="## Context and Problem Statement\n\nWhy.\n"),
            "unknown section": document(body=good_body.replace("## Considered", "## Surprise\n\nx\n\n## Considered")),
            "duplicate section": document(body=good_body + "\n## Considered Options\n\n* C\n"),
            "missing context": document(body=good_body.replace("## Context and Problem Statement\n\nWhy.\n\n", "")),
            "missing options": document(body=good_body.replace("## Considered Options\n\n* A\n* B\n\n", "")),
            "missing outcome": document(body=good_body.split("## Decision Outcome")[0]),
            "outcome not in the template form": document(body=good_body.replace("Chosen option:", "We pick")),
            "chosen not among options": document(body=good_body.replace('"A"', '"Z"')),
            "option not a bullet": document(body=good_body.replace("* A\n* B", "A and B")),
            "empty section": document(body=good_body.replace("Why.", "")),
        }
        for label, text in cases.items():
            path = self.put("DR-001-case.md", text)
            with self.subTest(label), self.assertRaises(dr.DecisionRecordError) as caught:
                dr.read_decision(path)
            self.assertIn("DR-001-case.md", str(caught.exception), label)

    def test_decision_makers_are_optional_and_read_as_none_when_absent(self) -> None:
        path = self.put("DR-001-a.md", document("status: accepted\ndate: 2026-10-26\n"))
        self.assertEqual(dr.read_decision(path).decision_makers, ())

    def test_an_old_form_decision_is_refused_naming_the_expected_shape(self) -> None:
        old = self.put("DR-001.md", "Status: APPROVED\n\n# DR-001 Gate\n\nThe user approved v1.\n")
        for call in (lambda: dr.read_decision(old), lambda: dr.read_decisions(self.dir),
                     lambda: dr.find_decision(self.dir, "DR-001")):
            with self.assertRaisesRegex(dr.DecisionRecordError, r"DR-001\.md.*DR-###-slug\.md.*MADR 4\.0\.0"):
                call()

    def test_a_slugged_file_without_front_matter_is_refused_naming_the_expected_shape(self) -> None:
        path = self.put("DR-001-gate.md", "Status: APPROVED\n\n# DR-001 Gate\n")
        with self.assertRaisesRegex(dr.DecisionRecordError, r"DR-001-gate\.md.*MADR 4\.0\.0 YAML front matter"):
            dr.read_decision(path)

    def test_a_front_matter_key_given_twice_is_refused_naming_the_key(self) -> None:
        for front in ("status: rejected\nstatus: accepted\ndate: 2026-10-26\n",
                      "status: accepted\ndate: 2026-10-26\ndate: 2026-10-27\n"):
            path = self.put("DR-001-twice.md", document(front))
            with self.subTest(front), self.assertRaisesRegex(dr.DecisionRecordError,
                                                             r"DR-001-twice\.md.*(status|date).*twice"):
                dr.read_decision(path)

    def test_a_sequence_or_mapping_as_a_front_matter_key_is_refused_naming_the_file(self) -> None:
        for key in ("[a, b]", "{a: b}"):
            path = self.put("DR-001-unhashable.md", document(f"status: accepted\ndate: 2026-10-26\n? {key}\n: x\n"))
            with self.subTest(key), self.assertRaisesRegex(dr.DecisionRecordError,
                                                           r"DR-001-unhashable\.md.*YAML front matter is invalid"):
                dr.read_decision(path)

    def test_a_front_matter_the_yaml_constructors_cannot_convert_is_refused_naming_the_file(self) -> None:
        base = "status: accepted\ndate: 2026-10-26\n"
        cases = {
            "tagged boolean": "status: !!bool maybe\ndate: 2026-10-26\n",
            "tagged timestamp": base + "x: !!timestamp not-a-time\n",
            "empty tagged int": base + 'x: !!int ""\n',
            "empty tagged float": base + 'x: !!float ""\n',
            "sequence tagged as a map": base + "x: !!map [a]\n",
            "sequence tagged as a set": base + "x: !!set [a]\n",
            "excessive nesting": base + "x: " + "[" * 5000 + "]" * 5000 + "\n",
            "long sexagesimal float": base + "x: !!float " + ":".join(["1"] * 6000) + "\n",
        }
        for label, front in cases.items():
            path = self.put("DR-001-yaml.md", document(front))
            with self.subTest(label), self.assertRaisesRegex(dr.DecisionRecordError,
                                                             r"DR-001-yaml\.md.*YAML front matter is invalid"):
                dr.read_decision(path)

    def test_a_huge_integer_key_or_status_is_refused_with_a_bounded_message(self) -> None:
        huge = "0x" + "f" * 4000
        for label, front in (("key", f"status: accepted\ndate: 2026-10-26\n? {huge}\n: x\n"),
                             ("status", f"status: {huge}\ndate: 2026-10-26\n"),
                             ("long text status", f"status: {'z' * 5000}\ndate: 2026-10-26\n")):
            path = self.put("DR-001-huge.md", document(front))
            with self.subTest(label), self.assertRaises(dr.DecisionRecordError) as caught:
                dr.read_decision(path)
            self.assertIn("DR-001-huge.md", str(caught.exception))
            self.assertLess(len(str(caught.exception)), 1000)

    def test_an_oversized_diagnostic_value_is_cut_in_the_message_naming_the_file(self) -> None:
        keys = "".join(f"unknown-key-{index}-{'k' * 100}: x\n" for index in range(200))
        cases = {
            "superseded-by": ("status: accepted\ndate: 2026-10-26\nsuperseded-by: [" + "d" * 5000 + "]\n", "d" * 61),
            "tagged boolean": ("status: !!bool " + "b" * 5000 + "\ndate: 2026-10-26\n", "b" * 201),
            "unknown keys": ("status: accepted\ndate: 2026-10-26\n" + keys, "unknown-key-11-"),
        }
        for label, (front, leaked) in cases.items():
            path = self.put("DR-001-long.md", document(front))
            with self.subTest(label), self.assertRaises(dr.DecisionRecordError) as caught:
                dr.read_decision(path)
            message = str(caught.exception)
            self.assertIn("DR-001-long.md", message)
            self.assertLess(len(message), 1500)
            self.assertNotIn(leaked, message)

    def test_an_impossible_calendar_date_is_refused_naming_the_file(self) -> None:
        path = self.put("DR-001-date.md", document("status: accepted\ndate: 2026-13-45\n"))
        with self.assertRaisesRegex(dr.DecisionRecordError, r"DR-001-date\.md.*YAML front matter is invalid"):
            dr.read_decision(path)

    def test_unknown_front_matter_keys_of_mixed_types_are_refused_naming_the_file(self) -> None:
        path = self.put("DR-001-keys.md", document("status: accepted\ndate: 2026-10-26\n1: one\nz: zed\n"))
        with self.assertRaisesRegex(dr.DecisionRecordError, r"DR-001-keys\.md.*unknown front matter keys"):
            dr.read_decision(path)

    def test_a_number_above_999_is_refused(self) -> None:
        with self.assertRaises(dr.DecisionRecordError):
            dr.write_decision(self.dir, number=1000, **MINIMAL)

    def test_a_decision_file_with_a_non_madr_name_is_refused(self) -> None:
        for name in ("DR-001.md", "DR-1-x.md", "DR-001-Upper.md", "DR-001-x-.md"):
            with self.subTest(name):
                directory = self.dir / name
                directory.mkdir()
                (directory / name).write_text(document(), encoding="utf-8")
                with self.assertRaisesRegex(dr.DecisionRecordError, name):
                    dr.read_decisions(directory)

    def test_a_superseded_by_that_names_no_record_is_refused_by_the_directory_read(self) -> None:
        self.put("DR-001-a.md", document("status: accepted\ndate: 2026-10-26\ndecision-makers: [A]\n"
                                         "superseded-by: [DR-002]\n"))
        self.assertEqual(dr.read_decision(self.dir / "DR-001-a.md").superseded_by, ("DR-002",))
        with self.assertRaisesRegex(dr.DecisionRecordError, "DR-001-a.md.*DR-002"):
            dr.read_decisions(self.dir)
        self.put("DR-002-b.md", document())
        self.assertEqual([r.id for r in dr.read_decisions(self.dir)], ["DR-001", "DR-002"])

    def test_two_records_with_one_number_are_refused(self) -> None:
        self.put("DR-001-a.md", document())
        self.put("DR-001-b.md", document())
        with self.assertRaisesRegex(dr.DecisionRecordError, "DR-001"):
            dr.read_decisions(self.dir)

    def test_a_non_utf8_file_is_refused(self) -> None:
        path = self.dir / "DR-001-a.md"
        path.write_bytes(b"---\n\xff\n---\n")
        with self.assertRaises(dr.DecisionRecordError):
            dr.read_decision(path)

    def test_the_file_number_names_the_record_not_the_title(self) -> None:
        path = self.put("DR-007-a-b.md", document())
        record = dr.read_decision(path)
        self.assertEqual((record.number, record.slug), (7, "a-b"))


class FindTests(Base):
    def test_find_decision_returns_the_record_with_that_id(self) -> None:
        dr.write_decision(self.dir, **MINIMAL)
        dr.write_decision(self.dir, **{**MINIMAL, "title": "Second"})
        record = dr.find_decision(self.dir, "DR-002")
        self.assertEqual((record.id, record.title), ("DR-002", "Second"))

    def test_find_decision_refuses_an_unknown_or_malformed_id(self) -> None:
        dr.write_decision(self.dir, **MINIMAL)
        for ident in ("DR-009", "DR-1", "dr-001", "DR-001-use-aluminium", "../DR-001"):
            with self.subTest(ident), self.assertRaises(dr.DecisionRecordError):
                dr.find_decision(self.dir, ident)

    def test_find_decision_reads_only_the_record_it_names(self) -> None:
        dr.write_decision(self.dir, **MINIMAL)
        self.put("DR-002-bad.md", "not a record")
        self.assertEqual(dr.find_decision(self.dir, "DR-001").id, "DR-001")
        with self.assertRaisesRegex(dr.DecisionRecordError, "DR-002-bad.md"):
            dr.find_decision(self.dir, "DR-002")

    def test_find_decision_refuses_two_files_with_one_id(self) -> None:
        self.put("DR-001-a.md", document())
        self.put("DR-001-b.md", document())
        with self.assertRaisesRegex(dr.DecisionRecordError, "DR-001"):
            dr.find_decision(self.dir, "DR-001")


class IndexTests(Base):
    def test_writing_regenerates_an_index_listing_every_record_by_number(self) -> None:
        dr.write_decision(self.dir, **FULL)
        dr.write_decision(self.dir, **{**MINIMAL, "date": datetime.date(2026, 11, 1)})
        text = (self.dir / dr.INDEX_NAME).read_text(encoding="utf-8")
        self.assertIn("generated", text.splitlines()[0].lower())
        rows = [line for line in text.splitlines() if line.startswith("| [DR-")]
        self.assertEqual(rows, [
            "| [DR-001](DR-001-press-fit-pivot-pins.md) | Press-fit pivot pins | accepted | 2026-10-26 |",
            "| [DR-002](DR-002-use-aluminium.md) | Use aluminium | proposed | 2026-11-01 |"])

    def test_a_hand_edit_of_the_index_is_overwritten_by_the_next_write(self) -> None:
        dr.write_decision(self.dir, **MINIMAL)
        index = self.dir / dr.INDEX_NAME
        index.write_text("hand edited", encoding="utf-8")
        dr.write_decision(self.dir, **{**MINIMAL, "title": "Second"})
        self.assertIn("DR-002", index.read_text(encoding="utf-8"))

    def test_a_pipe_in_a_title_does_not_break_its_table_row(self) -> None:
        dr.write_decision(self.dir, **{**MINIMAL, "title": "A | B"})
        row = next(line for line in (self.dir / dr.INDEX_NAME).read_text(encoding="utf-8").splitlines()
                   if line.startswith("| [DR-"))
        self.assertIn("A \\| B", row)

    def test_a_malformed_existing_record_stops_the_write_and_changes_nothing(self) -> None:
        self.put("DR-001-bad.md", "not a record")
        with self.assertRaisesRegex(dr.DecisionRecordError, "DR-001-bad.md"):
            dr.write_decision(self.dir, **MINIMAL)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["DR-001-bad.md"])

    def test_regenerate_index_alone_rebuilds_it_from_the_records(self) -> None:
        dr.write_decision(self.dir, **MINIMAL)
        (self.dir / dr.INDEX_NAME).unlink()
        dr.regenerate_index(self.dir)
        self.assertIn("DR-001", (self.dir / dr.INDEX_NAME).read_text(encoding="utf-8"))


class LampArmExample(unittest.TestCase):
    def test_the_example_project_decisions_are_madr_records_and_dr_003_is_superseded_by_dr_004(self) -> None:
        records = dr.read_decisions(SKILL.parents[1] / "examples" / "lamp-arm" / "hw" / "decisions")
        self.assertEqual([r.id for r in records], ["DR-001", "DR-002", "DR-003", "DR-004", "DR-005", "DR-010"])
        self.assertEqual({r.status for r in records}, {"accepted"})
        self.assertEqual({r.id: r.superseded_by for r in records if r.superseded_by}, {"DR-003": ("DR-004",)})


LINE = st.text(alphabet=string.ascii_letters + string.digits + " .,;:!?'()-_/\u00e9\u4e2d", min_size=1, max_size=30
               ).map(str.strip).filter(bool)
PROSE = st.lists(LINE, min_size=1, max_size=4).map("\n\n".join)


@st.composite
def inputs(draw: st.DrawFn) -> dict[str, Any]:
    options = tuple(draw(st.lists(LINE, min_size=1, max_size=4, unique=True)))
    optional_text = st.one_of(st.none(), PROSE)
    return {
        "title": draw(LINE.filter(lambda t: any(c in string.ascii_letters + string.digits for c in t))),
        "status": draw(st.sampled_from(["proposed", "accepted", "rejected", "deprecated", "deprecated"])),
        "date": draw(st.dates(min_value=datetime.date(2000, 1, 1), max_value=datetime.date(2100, 12, 31))),
        "decision_makers": tuple(draw(st.lists(LINE, max_size=3))),
        "consulted": tuple(draw(st.lists(LINE, max_size=2))),
        "informed": tuple(draw(st.lists(LINE, max_size=2))),
        "context": draw(PROSE),
        "drivers": tuple(draw(st.lists(LINE, max_size=3))),
        "options": options,
        "chosen": draw(st.sampled_from(options)),
        "justification": draw(LINE),
        "consequences": draw(optional_text),
        "confirmation": draw(optional_text),
        "more_information": draw(optional_text),
    }


class RoundTripProperty(unittest.TestCase):
    @given(inputs())
    @example({**MINIMAL, "title": "yes", "decision_makers": ("null", "1.5", "a: b", "- x", "#c")})
    def test_whatever_is_written_reads_back_unchanged(self, given_inputs: dict[str, Any]) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = dr.write_decision(Path(tmp), **given_inputs)
            record = dr.read_decision(path)
            for key, value in given_inputs.items():
                self.assertEqual(getattr(record, key), value, key)
            self.assertEqual(dr.read_decisions(Path(tmp)), [record])


if __name__ == "__main__":
    unittest.main()
