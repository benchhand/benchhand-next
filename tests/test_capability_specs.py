# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""tools/specs: the spec front matter, its cross references, Phase 2 coverage, the block graph and the page."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from capability_specs.cli import REPO_ROOT, run
from capability_specs.render import waves
from capability_specs.specs import (
    CATALOGUE_FILE,
    INDEX_FILE,
    PAGE_FILE,
    REGISTER_FILE,
    SPECS_DIR,
    SpecError,
    load_index,
    load_specs,
)
from mermaid_render import mermaid_blocks, needs_mermaid, render_markdown

POINTED = "docs/plan.md"
"""A five-line file the fixture's requirements point into."""

Spec = dict[str, Any]


def _catalogue() -> dict[str, Any]:
    return {
        "open_questions": [
            {"id": "which-gate", "blocking": True, "owner": "project-owner"},
            {"id": "where-bundle", "blocking": False},
        ],
        "capabilities": [
            {
                "id": "engine",
                "title": "Engine",
                "phase": 2,
                "status": "planned",
                "prototype": ["skills/flow/"],
            },
            {
                "id": "decisions",
                "title": "Decisions",
                "phase": 2,
                "status": "planned",
                "prototype": ["skills/dr.py"],
            },
            {"id": "snapshots", "title": "Snapshots", "phase": 2, "status": "planned"},
            {"id": "store", "title": "Store", "phase": 1, "status": "built"},
            {"id": "viewer", "title": "Viewer", "phase": 5, "status": "planned"},
        ],
    }


def _register() -> dict[str, Any]:
    return {
        "design_rules": [{"id": "RULE-05"}],
        "issues": [
            _issue("IR-001", ["skills/flow/stages.py"]),
            _issue("IR-002", ["skills/dr.py"]),
            _issue("IR-003", ["skills/other.py"]),
            {**_issue("IR-004", ["skills/flow/old.py"]), "benchhand_next": {"phase": 4}},
        ],
    }


def _issue(issue: str, paths: list[str]) -> dict[str, Any]:
    return {
        "id": issue,
        "title": f"Title of {issue}.",
        "disposition": "port-fix",
        "prototype_paths": paths,
        "benchhand_next": {"phase": 2},
    }


def _engine() -> Spec:
    return {
        "spec": "engine",
        "title": "The engine",
        "status": "draft",
        "capabilities": ["engine"],
        "questions": ["which-gate"],
        "rules": ["RULE-05"],
        "issues": {
            "closes": [{"id": "IR-001", "block": "EN-1", "test": "test_a_stage_advances"}],
            "defers": [],
        },
        "blocks": [
            {
                "id": "EN-1",
                "title": "Load the flow",
                "size": "M",
                "requirements": ["REQ-1"],
                "depends_on": [],
            },
            {
                "id": "EN-2",
                "title": "Gates",
                "size": "S",
                "requirements": ["REQ-2"],
                "depends_on": ["EN-1", "DR-1", "question:which-gate"],
            },
        ],
    }


def _decisions() -> Spec:
    return {
        "spec": "decisions",
        "title": "Decisions",
        "status": "draft",
        "capabilities": ["decisions", "store"],
        "questions": [],
        "rules": [],
        "issues": {
            "closes": [{"id": "IR-002", "block": "DR-1", "test": "test_a_decision_is_written"}],
            "defers": [],
        },
        "blocks": [
            {
                "id": "DR-1",
                "title": "Write decisions",
                "size": "L",
                "requirements": ["REQ-1"],
                "depends_on": ["capability:snapshots"],
            }
        ],
    }


BODIES = {
    "engine": [
        "# The engine",
        "## Requirements",
        "- **REQ-1.** The flow loads. Source: `docs/plan.md:2`.",
        "- **REQ-2.** A gate holds",
        "  until the user answers (IR-001).",
        "## Blocks",
        "### EN-1: Load the flow",
        "",
        "**Scope.** The loader. **Acceptance.** A load test.",
        "",
        "### EN-2: Gates",
        "",
        "**Scope.** Gates, `docs/plan.md:1-5`. **Acceptance.** A gate test.",
    ],
    "decisions": [
        "# Decisions",
        "## Requirements",
        "- **REQ-1.** A decision is written. **Proposal** for the owner.",
        "## Blocks",
        "### DR-1: Write decisions",
        "",
        "**Scope.** The writer. **Acceptance.** A writer test.",
    ],
}


class Repo:
    """A repository with the fixture's catalogue, register, index and specs, which a test edits and then checks."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.catalogue = _catalogue()
        self.register = _register()
        self.index: dict[str, Any] = {"specs": ["engine", "decisions"], "not_yet_specced": ["snapshots"]}
        self.specs = {"engine": _engine(), "decisions": _decisions()}
        self.bodies = copy.deepcopy(BODIES)

    def write(self) -> None:
        (self.root / SPECS_DIR).mkdir(parents=True, exist_ok=True)
        (self.root / "docs/architecture").mkdir(parents=True, exist_ok=True)
        (self.root / "docs/migration").mkdir(parents=True, exist_ok=True)
        (self.root / POINTED).write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
        (self.root / CATALOGUE_FILE).write_text(yaml.safe_dump(self.catalogue), encoding="utf-8")
        (self.root / REGISTER_FILE).write_text(yaml.safe_dump(self.register), encoding="utf-8")
        (self.root / INDEX_FILE).write_text(_document(self.index, ["# Specs"]), encoding="utf-8")
        for spec_id, front in self.specs.items():
            body = self.bodies.get(spec_id, [f"# {spec_id}"])
            (self.root / SPECS_DIR / f"{spec_id}.md").write_text(_document(front, body), encoding="utf-8")

    def check(self) -> list[str]:
        """The problems of a check with a freshly written page; empty when the specs hold together."""
        self.write()
        try:
            run(self.root, write=True)
        except SpecError as error:
            return error.problems
        return []


def _document(front: dict[str, Any], body: list[str]) -> str:
    return "---\n" + yaml.safe_dump(front, sort_keys=False) + "---\n" + "\n".join(body) + "\n"


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path)


def _problems_after(repo: Repo, change: Callable[[Repo], None]) -> str:
    change(repo)
    return "\n".join(repo.check())


def test_the_fixture_holds_together(repo: Repo) -> None:
    assert repo.check() == []


def test_the_specs_in_the_repository_hold_together_and_their_page_is_current() -> None:
    assert run(REPO_ROOT, write=False).startswith("specs: ")


def test_the_index_and_the_page_are_where_the_justfile_expects() -> None:
    assert (REPO_ROOT / INDEX_FILE).is_file()
    assert (REPO_ROOT / PAGE_FILE).is_file()


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (
            lambda r: r.specs["engine"]["capabilities"].append("nowhere"),
            "capability nowhere is not in the catalogue",
        ),
        (
            lambda r: r.specs["engine"]["questions"].append("unasked"),
            "question unasked is not in the catalogue",
        ),
        (
            lambda r: r.specs["engine"]["rules"].append("RULE-99"),
            "design rule RULE-99 is not in the issue register",
        ),
        (
            lambda r: r.specs["engine"]["issues"]["closes"].append(
                {"id": "IR-999", "block": "EN-1", "test": "t"}
            ),
            "issue IR-999 is not in the issue register",
        ),
        (
            lambda r: r.specs["engine"]["issues"]["defers"].append(
                {"id": "IR-003", "to": "nobody", "reason": "r"}
            ),
            "IR-003 is deferred to nobody, which is not a capability",
        ),
    ],
)
def test_an_id_that_doesnt_exist_is_a_problem(
    repo: Repo, change: Callable[[Repo], None], problem: str
) -> None:
    assert problem in _problems_after(repo, change)


@pytest.mark.parametrize(
    ("pointer", "problem"),
    [
        ("docs/plan.md:6", "docs/plan.md:6: docs/plan.md has 5 lines"),
        ("docs/plan.md:4-9", "docs/plan.md:4-9: docs/plan.md has 5 lines"),
        ("docs/plan.md:0", "docs/plan.md has 5 lines"),
        ("docs/missing.md:1", "no file docs/missing.md"),
        ("../outside.md:1", "a pointer stays inside the repository"),
        ("/abs/plan.md:3", "a pointer is a path relative to the repository"),
        ("~/plan.md:1", "a pointer is a path relative to the repository"),
        ("docs/plan.md:4-", "not a `path:line` or `path:first-last` pointer"),
        ("docs/plan.md:4-2", "the range runs backwards"),
    ],
)
def test_a_pointer_that_doesnt_resolve_is_a_problem_on_its_line(
    repo: Repo, pointer: str, problem: str
) -> None:
    repo.bodies["engine"][2] = f"- **REQ-1.** The flow loads. Source: `{pointer}`."
    problems = "\n".join(repo.check())
    lines = (repo.root / SPECS_DIR / "engine.md").read_text(encoding="utf-8").splitlines()
    line = next(number for number, text in enumerate(lines, start=1) if pointer in text)
    assert f"{SPECS_DIR}/engine.md:{line}: {pointer}" in problems
    assert problem in problems


def test_a_span_that_isnt_a_pointer_is_not_checked(repo: Repo) -> None:
    repo.bodies["engine"].append("`flow.yaml#/gates/0` and `containers.md:flowEngine` and `hw/policy.yaml`.")
    assert repo.check() == []


def test_a_phase_2_capability_needs_a_spec_or_the_not_yet_specced_list(repo: Repo) -> None:
    assert "Phase 2 capability snapshots has no spec" in _problems_after(
        repo, lambda r: r.index["not_yet_specced"].clear()
    )


def test_a_capability_covered_by_two_specs_is_a_problem(repo: Repo) -> None:
    assert "capability engine is covered by 2 specs" in _problems_after(
        repo, lambda r: r.specs["decisions"]["capabilities"].append("engine")
    )


@pytest.mark.parametrize(
    ("name", "problem"),
    [
        ("engine", "not_yet_specced names engine, which a spec covers"),
        ("store", "not_yet_specced names store, which is not a Phase 2 capability"),
        ("nowhere", "not_yet_specced names nowhere, which is not a capability"),
    ],
)
def test_the_not_yet_specced_list_names_only_uncovered_phase_2_capabilities(
    repo: Repo, name: str, problem: str
) -> None:
    assert problem in _problems_after(repo, lambda r: r.index["not_yet_specced"].append(name))


def test_a_spec_file_the_index_doesnt_list_is_a_problem(repo: Repo) -> None:
    repo.write()
    (repo.root / SPECS_DIR / "stray.md").write_text("# Stray\n", encoding="utf-8")
    with pytest.raises(SpecError, match="docs/specs/stray.md: not listed"):
        run(repo.root, write=True)


def test_a_spec_the_index_lists_without_a_file_is_a_problem(repo: Repo) -> None:
    assert "lists spec ghost, but docs/specs/ghost.md doesn't exist" in _problems_after(
        repo, lambda r: r.index["specs"].append("ghost")
    )


def test_a_spec_whose_id_isnt_its_file_name_is_a_problem(repo: Repo) -> None:
    assert "its spec id is renamed" in _problems_after(
        repo, lambda r: r.specs["engine"].update(spec="renamed")
    )


def test_a_block_id_defined_twice_is_a_problem(repo: Repo) -> None:
    def twice(r: Repo) -> None:
        r.specs["decisions"]["blocks"][0]["id"] = "EN-1"
        r.specs["decisions"]["issues"]["closes"][0]["block"] = "EN-1"
        r.bodies["decisions"][4] = "### EN-1: Write decisions"
        r.specs["engine"]["blocks"][1]["depends_on"].remove("DR-1")

    assert "block EN-1 is defined 2 times" in _problems_after(repo, twice)


@pytest.mark.parametrize(
    ("target", "problem"),
    [
        ("XX-9", "depends on XX-9: no spec defines that block"),
        ("question:where-bundle", "depends on question:where-bundle: the spec's questions don't list it"),
        ("question:unasked", "depends on question:unasked: no such open question"),
        ("capability:decisions", "spec decisions covers it; depend on its block instead"),
        ("capability:nowhere", "depends on capability:nowhere: no such capability"),
    ],
)
def test_a_dependency_that_doesnt_resolve_is_a_problem(repo: Repo, target: str, problem: str) -> None:
    assert problem in _problems_after(
        repo, lambda r: r.specs["engine"]["blocks"][0]["depends_on"].append(target)
    )


def test_a_dependency_cycle_is_a_problem(repo: Repo) -> None:
    assert "block dependencies have a cycle: EN-1 -> EN-2 -> EN-1" in _problems_after(
        repo, lambda r: r.specs["engine"]["blocks"][0]["depends_on"].append("EN-2")
    )


def test_a_cycle_across_specs_is_a_problem(repo: Repo) -> None:
    assert "block dependencies have a cycle: EN-2 -> DR-1 -> EN-2" in _problems_after(
        repo, lambda r: r.specs["decisions"]["blocks"][0]["depends_on"].append("EN-2")
    )


def test_a_requirement_without_a_source_is_a_problem_on_its_line(repo: Repo) -> None:
    repo.bodies["engine"][3:5] = ["- **REQ-2.** A gate holds", "  until the user answers."]
    assert "docs/specs/engine.md:" in "\n".join(repo.check())
    assert "REQ-2 cites no source" in "\n".join(repo.check())


def test_a_pointer_to_a_file_without_a_line_is_no_source(repo: Repo) -> None:
    repo.bodies["decisions"][2] = "- **REQ-1.** A decision is written, as `docs/plan.md` says."
    assert "REQ-1 cites no source" in "\n".join(repo.check())


def test_a_requirement_defined_twice_is_a_problem(repo: Repo) -> None:
    repo.bodies["decisions"].insert(3, "- **REQ-1.** Again (IR-002).")
    assert "docs/specs/decisions.md: REQ-1 is defined 2 times" in "\n".join(repo.check())


def test_a_requirement_in_no_block_is_a_problem(repo: Repo) -> None:
    repo.bodies["decisions"].insert(3, "- **REQ-2.** Also (IR-002).")
    assert "REQ-2 is in no block" in "\n".join(repo.check())


def test_a_block_naming_a_requirement_the_spec_lacks_is_a_problem(repo: Repo) -> None:
    assert "block DR-1 names REQ-7, which the spec doesn't define" in _problems_after(
        repo, lambda r: r.specs["decisions"]["blocks"][0]["requirements"].append("REQ-7")
    )


def test_a_block_without_its_section_is_a_problem(repo: Repo) -> None:
    repo.bodies["decisions"][4] = "### Writing decisions"
    assert "block DR-1 has no `### DR-1` section" in "\n".join(repo.check())


@pytest.mark.parametrize("part", ["**Scope.**", "**Acceptance.**"])
def test_a_block_section_needs_its_scope_and_acceptance(repo: Repo, part: str) -> None:
    repo.bodies["decisions"][6] = repo.bodies["decisions"][6].replace(part, "")
    assert f"the section of block DR-1 has no {part}" in "\n".join(repo.check())


def test_a_section_for_a_block_the_front_matter_lacks_is_a_problem(repo: Repo) -> None:
    repo.bodies["decisions"] += ["", "### DR-2: Later", "", "**Scope.** x. **Acceptance.** y."]
    assert "section `### DR-2` names no block" in "\n".join(repo.check())


def test_a_closed_entry_needs_its_test(repo: Repo) -> None:
    del repo.specs["engine"]["issues"]["closes"][0]["test"]
    assert "'test' is a required property" in "\n".join(repo.check())


def test_a_closed_entry_names_a_block_of_its_spec(repo: Repo) -> None:
    assert "IR-001 is closed by block DR-1, which the spec doesn't define" in _problems_after(
        repo, lambda r: r.specs["engine"]["issues"]["closes"][0].update(block="DR-1")
    )


def test_an_entry_closed_twice_is_a_problem(repo: Repo) -> None:
    assert "IR-001 is closed by 2 entries" in _problems_after(
        repo,
        lambda r: r.specs["decisions"]["issues"]["closes"].append(
            {"id": "IR-001", "block": "DR-1", "test": "t"}
        ),
    )


def test_an_entry_both_closed_and_deferred_is_a_problem(repo: Repo) -> None:
    assert "IR-001 is both closed and deferred" in _problems_after(
        repo,
        lambda r: r.specs["engine"]["issues"]["defers"].append(
            {"id": "IR-001", "to": "snapshots", "reason": "r"}
        ),
    )


def test_a_deferral_to_a_specced_capability_needs_that_spec_to_close_it(repo: Repo) -> None:
    def defer(r: Repo) -> None:
        r.specs["engine"]["issues"]["defers"].append({"id": "IR-003", "to": "decisions", "reason": "r"})

    assert "IR-003 is deferred to decisions, but its spec decisions doesn't close it" in _problems_after(
        repo, defer
    )


def test_a_deferral_to_an_unspecced_capability_holds(repo: Repo) -> None:
    repo.specs["engine"]["issues"]["defers"].append({"id": "IR-003", "to": "snapshots", "reason": "r"})
    assert repo.check() == []


def test_a_joined_phase_2_entry_the_spec_doesnt_list_is_a_problem(repo: Repo) -> None:
    repo.register["issues"].append(_issue("IR-005", ["skills/flow/guide.md"]))
    assert "engine.md: Phase 2 entry IR-005 touches its capabilities; close or defer it" in "\n".join(
        repo.check()
    )


def test_an_entry_of_another_phase_or_path_is_not_joined(repo: Repo) -> None:
    repo.register["issues"].append({**_issue("IR-006", ["skills/flow/x.py"]), "benchhand_next": {"phase": 3}})
    repo.register["issues"].append(_issue("IR-007", ["skills/flowchart.py"]))
    assert repo.check() == []


def test_a_schema_problem_names_the_field(repo: Repo) -> None:
    repo.specs["engine"]["blocks"][0]["size"] = "XL"
    assert "front matter /blocks/0/size: 'XL' is not one of ['S', 'M', 'L']" in "\n".join(repo.check())


def test_a_spec_without_front_matter_is_a_problem(repo: Repo) -> None:
    repo.write()
    (repo.root / SPECS_DIR / "engine.md").write_text("# The engine\n", encoding="utf-8")
    with pytest.raises(SpecError, match="engine.md: no YAML front matter"):
        run(repo.root, write=True)


def test_a_stale_page_is_a_problem_and_write_refreshes_it(repo: Repo) -> None:
    assert repo.check() == []
    page = repo.root / PAGE_FILE
    page.write_text(page.read_text(encoding="utf-8") + "edited\n", encoding="utf-8")
    with pytest.raises(SpecError, match="phase-2.md is out of date"):
        run(repo.root, write=False)
    run(repo.root, write=True)
    assert run(repo.root, write=False).startswith("specs: 2 specs, 3 blocks (1 S, 1 M, 1 L)")


def test_the_page_indexes_every_phase_2_capability_and_the_entries_no_spec_closes(repo: Repo) -> None:
    repo.specs["engine"]["issues"]["defers"].append({"id": "IR-003", "to": "snapshots", "reason": "r"})
    assert repo.check() == []
    page = (repo.root / PAGE_FILE).read_text(encoding="utf-8")
    assert (
        "| [snapshots](../architecture/capabilities.md#snapshots) | Snapshots | planned | not yet specced |"
        in page
    )
    assert (
        "| [engine](../architecture/capabilities.md#engine) | Engine | planned | [engine](engine.md) |"
        in page
    )
    assert "`store` (decisions)" in page
    assert "| IR-003 | port-fix | snapshots | Title of IR-003. |" in page
    assert "IR-001 |" not in page
    assert "| [which-gate](../architecture/capabilities.md#which-gate) | yes | project-owner | EN-2 |" in page


def test_the_suggested_order_puts_each_block_in_the_wave_after_what_it_needs(repo: Repo) -> None:
    assert repo.check() == []
    specs = load_specs(repo.root, load_index(repo.root))
    assert [[block["id"] for block in wave] for wave in waves(specs)] == [["EN-1", "DR-1"], ["EN-2"]]
    assert (
        "### Wave 2\n\n- **EN-2** (S, engine): Gates. After EN-1, DR-1. Waits on `which-gate` (blocking)."
        in (repo.root / PAGE_FILE).read_text(encoding="utf-8")
    )


@needs_mermaid
def test_the_block_graph_renders(tmp_path: Path) -> None:
    text = (REPO_ROOT / PAGE_FILE).read_text(encoding="utf-8")
    assert mermaid_blocks(text) == 1
    assert len(render_markdown(text, tmp_path)) == 1


def test_an_invented_register_id_is_no_source_and_a_problem_on_its_line(repo: Repo) -> None:
    repo.bodies["engine"][3:5] = ["- **REQ-2.** A gate holds", "  until the user answers. Source: IR-999."]
    problems = "\n".join(repo.check())
    assert "REQ-2 cites no source" in problems
    lines = (repo.root / SPECS_DIR / "engine.md").read_text(encoding="utf-8").splitlines()
    line = next(number for number, text in enumerate(lines, start=1) if "IR-999" in text)
    assert f"docs/specs/engine.md:{line}: IR-999 is not in the issue register" in problems


def test_an_invented_design_rule_anywhere_in_the_body_is_a_problem(repo: Repo) -> None:
    repo.bodies["engine"].append("The gates follow RULE-99.")
    assert "RULE-99 is not in the issue register" in "\n".join(repo.check())


def test_a_bad_pointer_next_to_a_good_source_is_still_a_problem(repo: Repo) -> None:
    repo.bodies["engine"][2] = "- **REQ-1.** The flow loads (IR-001), `docs/plan.md:2` and `/abs/plan.md:2`."
    assert "/abs/plan.md:2: a pointer is a path relative to the repository" in "\n".join(repo.check())


def test_a_pointer_that_doesnt_resolve_is_no_source(repo: Repo) -> None:
    repo.bodies["decisions"][2] = "- **REQ-1.** A decision is written, as `docs/plan.md:9` says."
    problems = "\n".join(repo.check())
    assert "REQ-1 cites no source" in problems
    assert "docs/plan.md:9: docs/plan.md has 5 lines" in problems


def test_a_front_matter_key_given_twice_is_a_problem_that_names_its_line(repo: Repo) -> None:
    repo.write()
    path = repo.root / SPECS_DIR / "engine.md"
    text = path.read_text(encoding="utf-8")
    # A second depends_on with a valid list would otherwise hide the first one's unknown block.
    text = text.replace("  depends_on: []\n", "  depends_on:\n  - XX-9\n  depends_on: []\n", 1)
    path.write_text(text, encoding="utf-8")
    line = next(number for number, row in enumerate(text.splitlines(), start=1) if row == "  depends_on: []")
    with pytest.raises(SpecError, match=f"engine.md:{line}: front matter key 'depends_on' is given twice"):
        run(repo.root, write=True)


def test_a_block_heading_given_twice_is_a_problem_even_when_the_two_halves_pass_together(repo: Repo) -> None:
    repo.bodies["decisions"][6:7] = [
        "**Scope.** The writer.",
        "",
        "### DR-1: Again",
        "",
        "**Acceptance.** A test.",
    ]
    assert "block DR-1 has 2 `### DR-1` sections, not one" in "\n".join(repo.check())


def test_a_malformed_requirement_bullet_is_a_problem(repo: Repo) -> None:
    repo.bodies["decisions"].insert(3, "- **REQ-2** has no period (IR-002).")
    assert "docs/specs/decisions.md:" in "\n".join(repo.check())
    assert "not a requirement bullet" in "\n".join(repo.check())


def test_a_requirement_outside_the_requirements_section_is_a_problem(repo: Repo) -> None:
    repo.bodies["decisions"].append("- **REQ-2.** A stray requirement (IR-002).")
    problems = "\n".join(repo.check())
    assert "not a requirement bullet" in problems
    assert "REQ-2 is defined" not in problems


def test_a_spec_without_a_requirements_section_is_a_problem(repo: Repo) -> None:
    repo.bodies["decisions"][1] = "## Needs"
    problems = "\n".join(repo.check())
    assert "decisions.md: no `## Requirements` section" in problems
    assert "block DR-1 names REQ-1, which the spec doesn't define" in problems


def test_one_entry_deferred_to_two_capabilities_is_a_problem(repo: Repo) -> None:
    repo.specs["engine"]["issues"]["defers"].append({"id": "IR-003", "to": "snapshots", "reason": "r"})
    repo.specs["decisions"]["issues"]["defers"].append({"id": "IR-003", "to": "viewer", "reason": "r"})
    assert "IR-003 is deferred to 2 capabilities: snapshots, viewer" in "\n".join(repo.check())


def test_two_specs_that_defer_one_entry_to_one_capability_hold(repo: Repo) -> None:
    repo.specs["engine"]["issues"]["defers"].append({"id": "IR-003", "to": "snapshots", "reason": "r"})
    repo.specs["decisions"]["issues"]["defers"].append({"id": "IR-003", "to": "snapshots", "reason": "r"})
    assert repo.check() == []


def test_an_entry_deferred_to_an_unspecced_capability_but_closed_by_another_spec_is_a_problem(
    repo: Repo,
) -> None:
    repo.specs["decisions"]["issues"]["closes"].append({"id": "IR-003", "block": "DR-1", "test": "t"})
    repo.specs["engine"]["issues"]["defers"].append({"id": "IR-003", "to": "snapshots", "reason": "r"})
    assert "IR-003 is deferred to snapshots, which no spec covers, but spec decisions closes it" in "\n".join(
        repo.check()
    )
