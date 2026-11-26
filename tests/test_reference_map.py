"""The function map from prototype to benchhand-next: its file, its check against a copy, its diagrams."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest
from mermaid_render import MERMAID_READY, MERMAID_SKIP_REASON, mermaid_blocks, render_markdown
from reference_map.cli import MAP_FILE, OUTPUT_FILE, REFERENCE_ENV, REPO_ROOT, run
from reference_map.coverage import check_coverage, check_homes, required_files
from reference_map.entries import MapError, load_map, pattern_regex
from reference_map.render import render_function_map

needs_mermaid = pytest.mark.skipif(not MERMAID_READY, reason=MERMAID_SKIP_REASON)

MAP = """\
reference_commit: abc1234
entries:
  - path: skills/cad-x/SKILL.md
    home: flow/guides/
    phase: 2
    status: planned
  - path: skills/cad-x/scripts/build.py
    home:
      - packages/benchhand-core/src/benchhand_core/jobs/process.py
      - providers/kernel-cadquery/
    phase: 4
    status: ported
  - path: skills/cad-x/scripts/legacy.py
    status: dropped
    reason: replaced by the kernel hook
  - path: skills/cad-x/schemas/
    home: contracts/record/
    phase: 1
    status: in-progress
    basis: inferred
"""


def _write_map(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "reference-map.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _tree(root: Path, *files: str) -> Path:
    for name in files:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("", encoding="utf-8")
    return root


def test_the_map_loads_homes_phases_statuses_and_reasons(tmp_path: Path) -> None:
    reference = load_map(_write_map(tmp_path, MAP))
    by_path = {entry.path: entry for entry in reference.entries}
    assert by_path["skills/cad-x/scripts/build.py"].homes[1] == "providers/kernel-cadquery/"
    assert by_path["skills/cad-x/SKILL.md"].homes == ("flow/guides/",)
    assert by_path["skills/cad-x/scripts/legacy.py"].reason == "replaced by the kernel hook"
    assert by_path["skills/cad-x/schemas/"].inferred
    assert {entry.area for entry in reference.entries} == {"cad-x"}


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ("  - path: a.py\n    status: dropped\n", "a dropped entry needs a `reason`"),
        ("  - path: a.py\n    status: maybe\n    home: x\n    phase: 1\n", "`status` must be one of"),
        ("  - path: a.py\n    status: planned\n    phase: 1\n", "`home` is a path or command"),
        (
            "  - path: a.py\n    status: planned\n    home: x\n    phase: 9\n",
            "`phase` is a number from 0 to 7",
        ),
        (
            "  - path: a.py\n    status: partial\n    home: x\n    phase: 1\n",
            "a partial entry needs a `note` naming what is left out",
        ),
        (
            "  - path: a.py\n    status: planned\n    home: x\n    phase: null\n",
            "an entry with no phase needs a `note` naming the open question",
        ),
        (
            "  - path: a.py\n    status: ported\n    home: x\n    phase: null\n    note: n\n",
            "only a planned entry may have no phase",
        ),
        ("  - path: a.py\n    status: planned\n    home: x\n", "`phase` is a number from 0 to 7"),
        ("  - path: a.py\n    status: planned\n    home: x\n    phase: 1\n    why: y\n", "unknown key `why`"),
        (
            "  - path: a.py\n    status: dropped\n    reason: r\n    home: x\n",
            "a dropped entry has no `home`",
        ),
        (
            "  - path: a.py\n    status: planned\n    home: x\n    phase: 1\n"
            "  - path: a.py\n    status: dropped\n    reason: r\n",
            "a.py has two entries",
        ),
    ],
)
def test_an_invalid_entry_is_reported(tmp_path: Path, entry: str, message: str) -> None:
    with pytest.raises(MapError, match=message):
        load_map(_write_map(tmp_path, f"reference_commit: abc\nentries:\n{entry}"))


def test_globs_stay_in_a_segment_and_a_trailing_slash_covers_a_directory() -> None:
    assert pattern_regex("skills/*/SKILL.md").match("skills/cad-x/SKILL.md")
    assert not pattern_regex("skills/*/SKILL.md").match("skills/cad-x/scripts/SKILL.md")
    assert pattern_regex("skills/*/scripts/**/*.py").match("skills/cad-x/scripts/pkg/mod.py")
    assert pattern_regex("skills/*/scripts/**/*.py").match("skills/cad-x/scripts/mod.py")
    assert pattern_regex("skills/cad-x/assets/").match("skills/cad-x/assets/viewer/index.html")
    assert not pattern_regex("skills/cad-x/assets/").match("skills/cad-x/assets2/a")


def test_a_prototype_file_without_an_entry_fails_and_tests_are_not_asked_for(tmp_path: Path) -> None:
    reference = load_map(_write_map(tmp_path, MAP))
    prototype = _tree(
        tmp_path / "proto",
        "skills/cad-x/SKILL.md",
        "skills/cad-x/scripts/build.py",
        "skills/cad-x/scripts/legacy.py",
        "skills/cad-x/scripts/new_script.py",
        "skills/cad-x/schemas/a.json",
        "skills/cad-x/tests/test_build.py",
        "harness/test_generate.py",
        "harness/generate.py",
        "agents/cad-a.md",
    )
    with pytest.raises(MapError) as raised:
        check_coverage(reference, [prototype])
    assert raised.value.problems == [
        "agents/cad-a.md: a prototype file with no entry",
        "harness/generate.py: a prototype file with no entry",
        "skills/cad-x/scripts/new_script.py: a prototype file with no entry",
    ]
    assert required_files({"skills/cad-x/tests/test_a.py", "harness/test_x.py", "harness/install.py"}) == [
        "harness/install.py"
    ]


def test_an_entry_for_a_path_that_is_gone_fails(tmp_path: Path) -> None:
    reference = load_map(_write_map(tmp_path, MAP))
    prototype = _tree(tmp_path / "proto", "skills/cad-x/SKILL.md", "skills/cad-x/scripts/build.py")
    with pytest.raises(MapError) as raised:
        check_coverage(reference, [prototype])
    assert raised.value.problems == [
        "skills/cad-x/scripts/legacy.py: names a path that doesn't exist in the reference copy",
        "skills/cad-x/schemas/: names a path that doesn't exist in the reference copy",
    ]


def test_a_skill_with_no_entry_and_a_file_with_two_entries_fail(tmp_path: Path) -> None:
    both = MAP + "  - path: skills/cad-x/scripts/*.py\n    status: dropped\n    reason: r\n"
    reference = load_map(_write_map(tmp_path, both))
    prototype = _tree(
        tmp_path / "proto",
        "skills/cad-x/SKILL.md",
        "skills/cad-x/scripts/build.py",
        "skills/cad-x/scripts/legacy.py",
        "skills/cad-x/schemas/a.json",
        "skills/cad-y/references/a.md",
    )
    with pytest.raises(MapError) as raised:
        check_coverage(reference, [prototype])
    build, legacy, glob = (
        "skills/cad-x/scripts/build.py",
        "skills/cad-x/scripts/legacy.py",
        "skills/cad-x/scripts/*.py",
    )
    assert raised.value.problems == [
        f"{build}: matched by 2 entries ({build}, {glob})",
        f"{legacy}: matched by 2 entries ({legacy}, {glob})",
        "skills/cad-y/: a prototype skill with no entry",
    ]


def test_an_entry_may_be_found_in_any_of_the_reference_roots(tmp_path: Path) -> None:
    reference = load_map(_write_map(tmp_path, MAP))
    copy = _tree(tmp_path / "copy", "skills/cad-x/SKILL.md", "skills/cad-x/scripts/build.py")
    imported = _tree(tmp_path / "imported", "skills/cad-x/scripts/legacy.py", "skills/cad-x/schemas/a.json")
    check_coverage(reference, [copy, imported])


def test_a_ported_entry_needs_its_home_in_this_repository(tmp_path: Path) -> None:
    reference = load_map(_write_map(tmp_path, MAP))
    with pytest.raises(MapError, match="ported, but providers/kernel-cadquery/ doesn't exist"):
        check_homes(reference, tmp_path)
    repo = _tree(
        tmp_path / "repo",
        "providers/kernel-cadquery/x",
        "packages/benchhand-core/src/benchhand_core/jobs/process.py",
    )
    check_homes(reference, repo)


PARTIAL_MAP = """\
reference_commit: abc1234
entries:
  - path: skills/cad-x/scripts/half.py
    home: packages/benchhand-core/src/benchhand_core/record/half.py
    phase: 1
    status: partial
    note: "Left out: the gates (Phase 2)."
  - path: skills/cad-x/assets/
    home: packages/benchhand-core/src/benchhand_core/record/
    phase: null
    status: planned
    note: "Waits on an open question."
"""


def test_a_partial_entry_needs_its_home_and_renders_apart_with_its_note(tmp_path: Path) -> None:
    reference = load_map(_write_map(tmp_path, PARTIAL_MAP))
    with pytest.raises(MapError, match="half.py: partial, but packages/.*/record/half.py doesn't exist"):
        check_homes(reference, tmp_path)
    text = render_function_map(reference)
    assert "class p0 partial" in text
    assert "classDef partial " in text
    assert "- `skills/cad-x/scripts/half.py`: Left out: the gates (Phase 2)." in text
    assert "| **all** | **2** | 1 | 0 | 1 | 0 | 0 |" in text


def test_an_entry_without_a_phase_has_an_open_arrow(tmp_path: Path) -> None:
    text = render_function_map(load_map(_write_map(tmp_path, PARTIAL_MAP)))
    assert 'p1 -->|"phase open"| h1' in text
    assert "Phase open:\n\n- `skills/cad-x/assets/`: Waits on an open question." in text


EXPECTED_FLOWCHART = textwrap.dedent(
    """\
    flowchart LR
        subgraph prototype["prototype: skills/cad-x"]
            p0["SKILL.md"]
            p1["scripts/build.py"]
            p2["scripts/legacy.py"]
            p3["schemas/"]
        end
        subgraph next["benchhand-next"]
            h0["flow/guides/"]
            h1["benchhand-core/jobs/process.py"]
            h2["providers/kernel-cadquery/"]
            h3["dropped: replaced by the kernel hook"]
            h4["contracts/record/"]
        end
        p0 -->|"P2"| h0
        p1 -->|"P4"| h1
        p1 -->|"P4"| h2
        p2 -. dropped .-> h3
        p3 -->|"P1"| h4
        class p0 planned
        class p1 ported
        class p2 dropped
        class p3 inprogress
        class h0 home
        class h1 home
        class h2 home
        class h3 dropped
        class h4 home
        classDef ported fill:#d8f3dc,stroke:#2d6a4f
        classDef partial fill:#f1faf3,stroke:#2d6a4f,stroke-width:2px,stroke-dasharray: 6 3
        classDef inprogress fill:#fff3bf,stroke:#b08900
        classDef planned fill:#e7f0fa,stroke:#3a6ea5
        classDef dropped fill:#eeeeee,stroke:#888888,stroke-dasharray: 4 3,color:#666666
        classDef home fill:#ffffff,stroke:#3a6ea5"""
)


def test_each_area_is_a_flowchart_with_phases_on_the_edges_and_dropped_items_apart(tmp_path: Path) -> None:
    text = render_function_map(load_map(_write_map(tmp_path, MAP)))
    assert text.split("```mermaid\n")[1].split("\n```")[0] == EXPECTED_FLOWCHART
    assert "| **all** | **4** | 1 | 1 | 0 | 1 | 1 |" in text


def test_the_committed_map_is_valid_and_its_diagrams_are_current() -> None:
    """Without a reference copy this checks the file, ported homes and the committed diagrams."""
    report = run(REPO_ROOT, None, write=False)
    assert "coverage not checked" in report


@pytest.mark.skipif(REFERENCE_ENV not in os.environ, reason=f"needs a prototype copy in ${REFERENCE_ENV}")
def test_every_prototype_script_and_skill_has_an_entry() -> None:
    assert f"coverage checked against {os.environ[REFERENCE_ENV]}" in run(
        REPO_ROOT, Path(os.environ[REFERENCE_ENV]), write=False
    )


@needs_mermaid
def test_every_flowchart_of_the_function_map_renders(tmp_path: Path) -> None:
    text = (REPO_ROOT / OUTPUT_FILE).read_text(encoding="utf-8")
    assert mermaid_blocks(text) > 10
    assert len(render_markdown(text, tmp_path)) == mermaid_blocks(text)


def test_the_map_file_and_the_diagram_file_are_where_the_justfile_expects() -> None:
    assert (REPO_ROOT / MAP_FILE).is_file()
    assert (REPO_ROOT / OUTPUT_FILE).is_file()
