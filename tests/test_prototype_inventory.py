# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The prototype inventory: what it reads from a prototype, how it joins the map, how it detects drift."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from prototype_inventory.build import (
    SCHEMA_VERSION,
    InventoryError,
    build_inventory,
    check_joined,
    count_commands,
    dump_json,
    find_entry,
)
from prototype_inventory.cli import JSON_FILE, MARKDOWN_FILE, REFERENCE_ENV, REPO_ROOT, run
from prototype_inventory.render import render_markdown
from prototype_inventory.scan import scan_source
from reference_map.entries import load_map

BUILD_PY = '''\
"""Build a part.

More about building.
"""

import sys


def build(part: str, *, count: int=1) -> dict[str, int]:
    """Build ``part`` ``count`` times.

    Longer text.
    """
    return {part: count}


async def fetch(url: str) -> bytes:
    return b""


def _private_helper() -> None:
    """Skipped: private."""


def undocumented(a, b=2, *rest, **options):
    def nested() -> None:
        """Skipped: nested."""


class Part(Base, metaclass=Meta):
    """A part."""

    def volume(self) -> float:
        """Its volume."""
        return 0.0

    def _hidden(self) -> None:
        """Skipped."""

    @property
    def mass(self) -> float:
        return 1.0


class _Internal:
    def visible_but_inside_private_class(self) -> None:
        pass


try:
    import fast
except ImportError:

    def fallback() -> None:
        """Defined in an import fallback."""


if __name__ == "__main__":
    sys.exit(build("x"))
'''

TOOL_PY = '''\
"""Run the tool."""

import argparse
from pathlib import Path

TABLE = (("--alpha", "a"), ("--beta", "b"))


def add_common(command: argparse.ArgumentParser) -> None:
    command.add_argument("--session", help="session name")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = root.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="check a record")
    check.add_argument("hw", type=Path)
    check.add_argument("--stage", choices=("a", "b"), help="the stage")
    add_common(check)
    for name in ("init", "build"):
        command = sub.add_parser(name)
        command.add_argument("--unit", required=True, help="unit id")
        if name == "init":
            command.add_argument("--reset", action="store_true")
        for flag in ("--x", "--y"):
            command.add_argument(flag, type=int)
    sub.add_parser("hidden", help=argparse.SUPPRESS)
    sub.add_parser("chained", help="chained").add_argument("path")
    run = sub.add_parser("run")
    group = run.add_mutually_exclusive_group()
    group.add_argument("--case")
    for option, field in TABLE:
        run.add_argument(option, dest=field)
    run.add_argument(compute(), help="computed")
    return root


if __name__ == "__main__":
    parser().parse_args()
'''

CLICK_PY = '''\
"""Click commands."""

import click

HW = click.argument("hw")
OUT = click.option("--out", "out_path", help="write here")


@click.group(help="Work on versions")
def cli() -> None:
    pass


@cli.command(help="build a version")
@HW
@click.option("--label", required=True, help="the label")
@click.option("--kernel", type=click.Choice(("auto", "cq")), default="auto")
@click.option("--attach", multiple=True)
def run_build(**params: object) -> int:
    return 0


@cli.command(name="diff")
@OUT
def compare() -> int:
    """Compare two versions."""
    return 0


@cli.group()
def store() -> None:
    pass


@store.command()
def gc() -> int:
    return 0
'''

MAP = """\
reference_commit: abc1234
entries:
  - path: skills/cad-x/scripts/build.py
    home: packages/benchhand-core/src/benchhand_core/jobs/build.py
    phase: 4
    status: ported
  - path: skills/cad-x/scripts/tool.py
    home: providers/kernel-cadquery/
    phase: 2
    status: planned
  - path: skills/cad-x/scripts/click_tool.py
    status: dropped
    reason: replaced
  - path: skills/cad-x/scripts/pkg/
    home: flow/
    phase: null
    status: planned
    note: waits on a question
  - path: harness/install.py
    home: harness/
    phase: 6
    status: planned
"""


def _tree(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


def _prototype(tmp_path: Path) -> Path:
    return _tree(
        tmp_path / "proto",
        {
            "skills/cad-x/scripts/build.py": BUILD_PY,
            "skills/cad-x/scripts/tool.py": TOOL_PY,
            "skills/cad-x/scripts/click_tool.py": CLICK_PY,
            "skills/cad-x/scripts/pkg/__init__.py": '"""A package."""\n',
            "skills/cad-x/scripts/test_build.py": "def test_x():\n    pass\n",
            "skills/cad-x/SKILL.md": "skill",
            "harness/install.py": "def install() -> None:\n    pass\n",
        },
    )


def _repo(tmp_path: Path) -> Path:
    return _tree(
        tmp_path / "repo",
        {
            "release.toml": 'reference_commit = "abc1234"\n',
            "docs/architecture/reference-map.yaml": MAP,
        },
    )


def _inventory(tmp_path: Path):
    reference = load_map(_repo(tmp_path) / "docs/architecture/reference-map.yaml")
    return build_inventory(_prototype(tmp_path), reference), reference


def _file(data, name: str):
    return next(file for file in data["files"] if file["path"].endswith(name))


def test_functions_classes_and_methods_are_read_with_signature_and_first_docstring_line() -> None:
    module = scan_source(BUILD_PY, "build.py")
    assert module["summary"] == "Build a part."
    by_name = {function["name"]: function for function in module["functions"]}
    assert by_name["build"]["signature"] == "def build(part: str, *, count: int=1) -> dict[str, int]"
    assert by_name["build"]["summary"] == "Build ``part`` ``count`` times."
    assert by_name["fetch"]["signature"] == "async def fetch(url: str) -> bytes"
    assert by_name["fetch"]["kind"] == "async function"
    assert by_name["undocumented"]["signature"] == "def undocumented(a, b=2, *rest, **options)"
    assert by_name["undocumented"]["summary"] == ""
    assert by_name["Part.volume"]["kind"] == "method"
    assert by_name["Part.mass"]["decorators"] == ["property"]
    assert by_name["fallback"]["summary"] == "Defined in an import fallback."
    assert [cls["signature"] for cls in module["classes"]] == ["class Part(Base, metaclass=Meta)"]


def test_private_names_and_nested_definitions_are_skipped() -> None:
    module = scan_source(BUILD_PY, "build.py")
    names = {function["name"] for function in module["functions"]}
    assert names == {"build", "fetch", "undocumented", "Part.volume", "Part.mass", "fallback"}
    assert [cls["name"] for cls in module["classes"]] == ["Part"]


def test_a_main_guard_is_an_entry_point() -> None:
    assert scan_source(BUILD_PY, "build.py")["entry_points"] == ["sys.exit(build('x'))"]
    assert scan_source("def f():\n    pass\n", "f.py")["entry_points"] == []


def test_argparse_subcommands_options_and_help_are_found_statically() -> None:
    commands = {c["command"]: c for c in scan_source(TOOL_PY, "tool.py")["commands"]}
    assert list(commands) == ["", "check", "init", "build", "hidden", "chained", "run"]
    assert commands[""]["summary"] == "Run the tool."
    check = commands["check"]
    assert check["summary"] == "check a record"
    assert [(o["flags"], o["kind"]) for o in check["options"]] == [
        (["hw"], "positional"),
        (["--stage"], "option"),
        (["--session"], "option"),
    ]
    assert check["options"][1].get("choices") == "('a', 'b')"
    assert check["options"][1]["help"] == "the stage"
    assert commands["hidden"]["hidden"] is True


def test_a_loop_over_literal_names_and_an_if_on_the_loop_variable_are_followed() -> None:
    commands = {c["command"]: c for c in scan_source(TOOL_PY, "tool.py")["commands"]}
    init = [o["flags"][0] for o in commands["init"]["options"]]
    build = [o["flags"][0] for o in commands["build"]["options"]]
    assert init == ["--unit", "--reset", "--x", "--y"]
    assert build == ["--unit", "--x", "--y"]
    assert commands["init"]["options"][0].get("required") is True


def test_options_added_through_a_chain_a_group_a_table_and_a_computed_flag() -> None:
    commands = {c["command"]: c for c in scan_source(TOOL_PY, "tool.py")["commands"]}
    assert [o["flags"] for o in commands["chained"]["options"]] == [["path"]]
    run_options = commands["run"]["options"]
    assert [o["flags"] for o in run_options] == [["--case"], ["--alpha"], ["--beta"], ["compute()"]]
    assert run_options[-1].get("dynamic") is True
    assert "dynamic" not in run_options[1]


def test_click_groups_commands_and_option_decorators_are_found() -> None:
    commands = {c["command"]: c for c in scan_source(CLICK_PY, "click_tool.py")["commands"]}
    assert list(commands) == ["", "run-build", "diff", "store", "store gc"]
    assert commands["run-build"]["summary"] == "build a version"
    options = commands["run-build"]["options"]
    assert [(o["flags"], o["kind"]) for o in options] == [
        (["hw"], "positional"),
        (["--label"], "option"),
        (["--kernel"], "option"),
        (["--attach"], "option"),
    ]
    assert options[2].get("choices") == "('auto', 'cq')"
    assert options[3].get("nargs") == "multiple"
    assert commands["diff"]["summary"] == "Compare two versions."
    assert commands["diff"]["options"][0].get("dest") == "'out_path'"
    assert {c["framework"] for c in commands.values()} == {"click"}


def test_only_commands_that_can_be_run_are_counted() -> None:
    assert count_commands(scan_source(TOOL_PY, "tool.py")["commands"]) == 6
    assert count_commands(scan_source(CLICK_PY, "click_tool.py")["commands"]) == 3
    assert count_commands([]) == 0


def test_each_file_joins_its_map_entry_and_its_functions_inherit_it(tmp_path: Path) -> None:
    data, _ = _inventory(tmp_path)
    build = _file(data, "build.py")
    assert build["home"] == ["packages/benchhand-core/src/benchhand_core/jobs/build.py"]
    assert (build["phase"], build["status"], build["area"]) == (4, "ported", "cad-x")
    assert _file(data, "click_tool.py")["status"] == "dropped"
    assert _file(data, "click_tool.py")["reason"] == "replaced"
    assert _file(data, "pkg/__init__.py")["phase"] is None
    assert _file(data, "install.py")["area"] == "agents-and-harness"


def test_the_inventory_covers_scripts_and_the_harness_but_not_tests_or_skill_text(tmp_path: Path) -> None:
    data, _ = _inventory(tmp_path)
    assert [file["path"] for file in data["files"]] == [
        "harness/install.py",
        "skills/cad-x/scripts/build.py",
        "skills/cad-x/scripts/click_tool.py",
        "skills/cad-x/scripts/pkg/__init__.py",
        "skills/cad-x/scripts/tool.py",
    ]


def test_summary_counts_files_commands_classes_functions_and_methods_per_area(tmp_path: Path) -> None:
    data, _ = _inventory(tmp_path)
    assert data["summary"]["by_area"]["cad-x"] == {
        "files": 4,
        "commands": 9,
        "classes": 1,
        "functions": 11,
        "methods": 2,
    }
    assert data["summary"]["by_area"]["agents-and-harness"]["functions"] == 1
    assert list(data["summary"]["by_area"]) == ["cad-x", "agents-and-harness"]
    assert data["summary"]["files"] == 5
    assert data["schema_version"] == SCHEMA_VERSION


def test_a_file_with_no_entry_or_with_two_fails(tmp_path: Path) -> None:
    _, reference = _inventory(tmp_path)
    with pytest.raises(InventoryError, match="matched by 0 reference-map entries"):
        find_entry("skills/cad-x/scripts/other.py", reference)
    both = MAP + "  - path: skills/cad-x/scripts/*.py\n    status: dropped\n    reason: r\n"
    (tmp_path / "repo/docs/architecture/reference-map.yaml").write_text(both, encoding="utf-8")
    two = load_map(tmp_path / "repo/docs/architecture/reference-map.yaml")
    with pytest.raises(InventoryError, match="build.py: matched by 2 reference-map entries"):
        build_inventory(tmp_path / "proto", two)


def test_a_file_that_does_not_parse_is_reported_by_name(tmp_path: Path) -> None:
    _, reference = _inventory(tmp_path)
    (tmp_path / "proto/skills/cad-x/scripts/tool.py").write_text("def broken(:\n", encoding="utf-8")
    with pytest.raises(InventoryError, match="skills/cad-x/scripts/tool.py: "):
        build_inventory(tmp_path / "proto", reference)


def test_output_is_deterministic_and_documented_as_generated(tmp_path: Path) -> None:
    first, _ = _inventory(tmp_path)
    second, _ = _inventory(tmp_path)
    assert dump_json(first) == dump_json(second)
    assert render_markdown(first) == render_markdown(second)
    assert json.loads(dump_json(first))["schema_version"] == SCHEMA_VERSION
    assert "Generated by tools/inventory" in json.loads(dump_json(first))["generated"]
    assert "Do not edit." in json.loads(dump_json(first))["generated"]
    lines = render_markdown(first).splitlines()
    assert lines[2].startswith("Generated by tools/inventory") and lines[2].endswith("Do not edit.")


def test_the_markdown_has_summary_counts_a_command_table_and_a_function_table(tmp_path: Path) -> None:
    data, _ = _inventory(tmp_path)
    text = render_markdown(data)
    assert "| Area | Files | Commands | Classes | Functions | Methods |" in text
    assert "| cad-x | 4 |" in text
    assert "## cad-x\n" in text
    assert "## agents and harness\n" in text
    assert "| Script | Command | Summary | Options |" in text
    assert "| `scripts/tool.py` | `check` | check a record | `<hw>`<br>`--stage`<br>`--session` |" in text
    assert "| File | Name | Signature | Summary | Home | Phase | Status |" in text
    row = (
        "| `scripts/build.py` | `build` | `def build(part: str, *, count: int=1) -> dict[str, int]` "
        "| Build ``part`` ``count`` times. | `benchhand-core/jobs/build.py` | P4 | ported |"
    )
    assert row in text.replace("\\`", "`")
    assert "`Part.volume`" in text
    assert text.index("`Part`") < text.index("`Part.volume`") < text.index("`fallback`")


def test_table_cells_escape_pipes(tmp_path: Path) -> None:
    data, _ = _inventory(tmp_path)
    _file(data, "build.py")["functions"][0]["signature"] = "def f(a: int | None) -> str | None"
    assert r"`def f(a: int \| None) -> str \| None`" in render_markdown(data)


def _write_all(tmp_path: Path) -> tuple[Path, Path]:
    repo, prototype = _repo(tmp_path), _prototype(tmp_path)
    (repo / "docs/architecture").mkdir(parents=True, exist_ok=True)
    report = run(repo, prototype, write=True)
    assert "5 files" in report
    return repo, prototype


def test_a_written_inventory_passes_the_check_with_and_without_a_copy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    repo, prototype = _write_all(tmp_path)
    assert "read from" in run(repo, prototype, write=False)
    assert "not re-read" in run(repo, None, write=False)


def test_a_changed_prototype_is_drift_when_the_copy_is_given(tmp_path: Path) -> None:
    repo, prototype = _write_all(tmp_path)
    script = prototype / "skills/cad-x/scripts/build.py"
    script.write_text(
        script.read_text(encoding="utf-8") + "\n\ndef added() -> None:\n    pass\n", encoding="utf-8"
    )
    with pytest.raises(InventoryError) as raised:
        run(repo, prototype, write=False)
    assert raised.value.problems == [
        f"{MARKDOWN_FILE} is out of date; run `just inventory --write` with BENCHHAND_REFERENCE_DIR set",
        f"{JSON_FILE} is out of date; run `just inventory --write` with BENCHHAND_REFERENCE_DIR set",
    ]


def test_an_edited_markdown_or_json_is_drift_without_a_copy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    repo, _ = _write_all(tmp_path)
    markdown = repo / MARKDOWN_FILE
    original = markdown.read_text(encoding="utf-8")
    markdown.write_text(original + "hand edit\n", encoding="utf-8")
    with pytest.raises(InventoryError, match="is not what .*json renders to"):
        run(repo, None, write=False)
    markdown.write_text(original, encoding="utf-8")
    (repo / JSON_FILE).write_text(
        (repo / JSON_FILE).read_text(encoding="utf-8").replace(" ", "  ", 1), encoding="utf-8"
    )
    with pytest.raises(InventoryError, match="not in the form the generator writes"):
        run(repo, None, write=False)


def test_a_changed_map_entry_is_drift_without_a_copy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    repo, _ = _write_all(tmp_path)
    changed = MAP.replace("phase: 4\n    status: ported", "phase: 5\n    status: ported")
    (repo / "docs/architecture/reference-map.yaml").write_text(changed, encoding="utf-8")
    with pytest.raises(
        InventoryError, match="build.py: its reference-map entry skills/cad-x/scripts/build.py changed"
    ):
        run(repo, None, write=False)


def test_a_missing_inventory_and_the_stale_pin_are_reported(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    repo = _repo(tmp_path)
    with pytest.raises(InventoryError, match="prototype-inventory.json is missing"):
        run(repo, None, write=False)
    (repo / "release.toml").write_text('reference_commit = "def"\n', encoding="utf-8")
    with pytest.raises(InventoryError, match="is not release.toml's def"):
        run(repo, None, write=False)


def test_writing_and_ci_need_a_prototype_copy(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(InventoryError, match=f"--write: set {REFERENCE_ENV}"):
        run(repo, None, write=True)
    monkeypatch.setenv("CI", "true")
    with pytest.raises(InventoryError, match=f"CI=true: set {REFERENCE_ENV}"):
        run(repo, None, write=False)


def test_check_joined_names_a_file_whose_entry_is_gone(tmp_path: Path) -> None:
    data, reference = _inventory(tmp_path)
    assert check_joined(data, reference) == []
    data["reference_commit"] = "old"
    data["files"][0]["path"] = "skills/cad-x/scripts/gone.py"
    assert check_joined(data, reference) == [
        "reference_commit old is not the map's abc1234",
        "skills/cad-x/scripts/gone.py: matched by 0 reference-map entries; expected one",
    ]


def test_the_committed_inventory_agrees_with_the_map_and_renders_to_the_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a prototype copy this checks the committed JSON against the map and the Markdown against the JSON."""
    monkeypatch.delenv("CI", raising=False)
    assert "not re-read" in run(REPO_ROOT, None, write=False)


def test_the_committed_inventory_matches_the_pinned_prototype() -> None:
    """Mandatory in CI, which fetches the pinned copy; skipped locally without one."""
    if REFERENCE_ENV not in os.environ:
        if os.environ.get("CI") == "true":
            pytest.fail(f"CI=true needs a prototype copy in ${REFERENCE_ENV}")
        pytest.skip(f"needs a prototype copy in ${REFERENCE_ENV}")
    assert "read from" in run(REPO_ROOT, Path(os.environ[REFERENCE_ENV]), write=False)


def test_the_generated_files_are_where_the_justfile_expects() -> None:
    assert (REPO_ROOT / MARKDOWN_FILE).is_file()
    assert (REPO_ROOT / JSON_FILE).is_file()
