#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""yaml_loader.safe_load against yaml.safe_load: the same value for every document yaml.safe_load reads,
and the same error, message included, for every document it refuses."""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

SKILL = Path(__file__).resolve().parents[1]
REPO = SKILL.parent.parent


def load(name: str, path: Path) -> Any:
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sys.modules[name])
    return sys.modules[name]


loader = load("cad_record_yaml_loader", SKILL / "scripts" / "yaml_loader.py")

# Documents libyaml reads and PyYAML's SafeLoader refuses or reads differently: tabs as separators, a
# byte order mark inside the document, `!` and `?` where PyYAML's grammar differs, and a comment straight
# after a block scalar indicator. Each was found by comparing the two parsers.
DIVERGENT = [
    "[a,\tb]",
    "{a: 1,\tb: 2}",
    "a:\t1",
    "a: [1,\t2]",
    "- a\t# c",
    "a: b\t",
    "[\ta]",
    "{\ta: 1}",
    "a: {b:\t1}",
    "key: 'x'\t",
    "a: [1, 2]\t# c",
    "a: [1,\n\t2]",
    "- [a]\t",
    "a:\n  - b\t\n",
    "[a\t, b]",
    "{a\t: 1}",
    "? a\t\n: b",
    "a: !!str\t1",
    "--- \t\na: 1",
    "a: &x\t1\nb: *x",
    "%YAML 1.1\t\n---\na: 1",
    "files: x[]\n\ufeff",
    "a: 1\n\ufeffb: 2",
    "! #c\nparent: LMP-0005\n",
    "a: >#c\n",
    "a: |#c\n  x\n",
    "a: |-#c\n  x",
    "a: >1#\n  x",
    "{a? b}",
    "[a? b]",
    "x: {a ? b}",
    "{a ?b}",
]
# Documents both parsers read alike, tabs inside quoted and block scalars included.
AGREEING = [
    "a: |\n  x\ty",
    'a: "x\ty"',
    "a: 'x\n\ty'",
    "\ta: 1",
    "a: x\n\ty",
    "a: [1, 2]",
    "{? a}",
    "! 12",
]


def outcome(read: Any) -> tuple[str, Any]:
    try:
        return "value", read()
    except yaml.YAMLError as error:
        return type(error).__name__, str(error)


class SameAsSafeLoad(unittest.TestCase):
    def assertSame(self, text: str) -> None:
        self.assertEqual(
            outcome(lambda: loader.safe_load(text)),
            outcome(lambda: yaml.safe_load(text)),
            repr(text),
        )

    def test_every_tracked_yaml_file_reads_as_yaml_safe_load_reads_it(self) -> None:
        files = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "*.yaml", "*.yml"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        self.assertGreater(len(files), 40)
        for rel in files:
            with self.subTest(rel=rel):
                self.assertSame((REPO / rel).read_text(encoding="utf-8"))

    def test_documents_libyaml_reads_differently_read_as_yaml_safe_load_reads_them(
        self,
    ) -> None:
        for text in DIVERGENT + AGREEING:
            with self.subTest(text=text):
                self.assertSame(text)

    def test_an_open_file_reads_as_yaml_safe_load_reads_it_and_its_errors_name_the_file(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="cad-yaml-loader-") as folder:
            for index, text in enumerate(
                ["a: [1, 2]\n", "a: [1,\t2]\n", "a: [1, 2\n", "a: |#c\n  x\n"]
            ):
                path = Path(folder) / f"doc-{index}.yaml"
                path.write_text(text, encoding="utf-8")
                with (
                    self.subTest(text=text),
                    path.open(encoding="utf-8") as mine,
                    path.open(encoding="utf-8") as theirs,
                ):
                    self.assertEqual(
                        outcome(lambda: loader.safe_load(mine)),
                        outcome(lambda: yaml.safe_load(theirs)),
                    )

    def test_bytes_and_unseekable_streams_read_as_yaml_safe_load_reads_them(
        self,
    ) -> None:
        class Unseekable(io.StringIO):
            def seekable(self) -> bool:
                return False

        for text in ("a: [1, 2]\n", "a: [1,\t2]\n", "a: [1, 2\n"):
            with self.subTest(text=text):
                self.assertEqual(
                    outcome(lambda: loader.safe_load(text.encode("utf-8"))),
                    outcome(lambda: yaml.safe_load(text.encode("utf-8"))),
                )
                self.assertEqual(
                    outcome(lambda: loader.safe_load(Unseekable(text))),
                    outcome(lambda: yaml.safe_load(io.StringIO(text))),
                )

    def test_a_stream_that_can_only_be_read_reads_as_yaml_safe_load_reads_it(self) -> None:
        class ReadOnly:
            """read() and nothing else: no seekable(), seek() or tell()."""

            def __init__(self, text: str) -> None:
                self._stream = io.StringIO(text)

            def read(self, size: int = -1) -> str:
                return self._stream.read(size)

        for text in ("a: [1, 2]\n", "a: [1,\t2]\n", "a: [1, 2\n"):
            with self.subTest(text=text):
                self.assertEqual(outcome(lambda: loader.safe_load(ReadOnly(text))),
                                 outcome(lambda: yaml.safe_load(ReadOnly(text))))


if __name__ == "__main__":
    unittest.main()
