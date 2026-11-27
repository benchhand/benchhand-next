# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The migrate rule table: each row turns its fixture's before/ tree into its after/ tree, byte for byte."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from benchhand_core.record.migrate import RULES, Rule, service

FIXTURES = Path(__file__).parent / "migrate_fixtures"


def _files(tree: Path) -> dict[str, bytes]:
    files = (path for path in tree.rglob("*") if path.is_file())
    return {path.relative_to(tree).as_posix(): path.read_bytes() for path in files}


def _run(rule: Rule, root: Path) -> list[str]:
    """Apply `rule` alone to every file it names under `root`; the findings, one line each."""
    findings = []
    for pattern in rule.documents:
        for file in sorted(root.glob(pattern)):
            path = file.relative_to(root).as_posix()
            rewrite = rule.run(path, file.read_bytes().decode("utf-8"))
            file.write_bytes(rewrite.text.encode("utf-8"))
            findings.extend(
                f"{finding.severity.value} {finding.code} {finding.path} {finding.pointer or ''}".rstrip()
                for finding in rewrite.findings
            )
    return findings


def test_every_rule_has_a_fixture_and_every_fixture_a_rule() -> None:
    assert sorted(rule.fixture for rule in RULES) == sorted(
        f"migrate_fixtures/{path.name}" for path in FIXTURES.iterdir() if path.is_dir()
    )
    assert len({rule.id for rule in RULES}) == len(RULES)


@pytest.mark.parametrize("rule", RULES, ids=[rule.id for rule in RULES])
def test_a_rule_turns_its_before_tree_into_its_after_tree(rule: Rule, tmp_path: Path) -> None:
    fixture = Path(__file__).parent / rule.fixture
    shutil.copytree(fixture / "before", tmp_path, dirs_exist_ok=True)
    findings = _run(rule, tmp_path)
    assert _files(tmp_path) == _files(fixture / "after")
    expected = fixture / "findings.txt"
    assert findings == (expected.read_text(encoding="utf-8").splitlines() if expected.exists() else [])


@pytest.mark.parametrize("rule", RULES, ids=[rule.id for rule in RULES])
def test_a_rule_changes_nothing_on_its_own_output(rule: Rule, tmp_path: Path) -> None:
    """Idempotence per row: an after/ tree is already migrated; only refused files may report again."""
    fixture = Path(__file__).parent / rule.fixture
    shutil.copytree(fixture / "after", tmp_path, dirs_exist_ok=True)
    _run(rule, tmp_path)
    assert _files(tmp_path) == _files(fixture / "after")


LAYOUTS = sorted(path.name for path in (Path(__file__).parent / "migrate_layout_fixtures").iterdir())


@pytest.mark.parametrize("case", LAYOUTS)
def test_a_layout_the_editor_cannot_locate_is_refused_naming_the_file_and_pointer(case: str) -> None:
    """Each file under migrate_layout_fixtures/<case>/ runs through every rule that names it, as the
    service runs it; the refusals are those in findings.txt, each with a hand fix."""
    fixture = Path(__file__).parent / "migrate_layout_fixtures" / case
    found = []
    for file in sorted(path for path in (fixture / "hw").rglob("*") if path.is_file()):
        path = file.relative_to(fixture).as_posix()
        _, findings = service._migrate_file(fixture, path)
        refusals = [finding for finding in findings if finding.severity.value == "error"]
        assert all(finding.action for finding in refusals)
        found.extend(f"error {f.code} {f.path} {f.pointer or ''}".rstrip() for f in refusals)
    assert found == (fixture / "findings.txt").read_text(encoding="utf-8").splitlines()
