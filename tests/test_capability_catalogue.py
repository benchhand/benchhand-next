# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""tools/catalogue: the capability catalogue's checks, its coverage of the prototype, and its page."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from capability_catalogue.catalogue import Catalogue, CatalogueError, load_catalogue
from capability_catalogue.checks import check_catalogue, cli_named, tool_named
from capability_catalogue.cli import CATALOGUE_FILE, OUTPUT_FILE, REPO_ROOT, run
from capability_catalogue.coverage import check_prototype_commands
from capability_catalogue.render import render_page
from mermaid_render import mermaid_blocks, needs_mermaid, render_markdown

BASE = "https://benchhand.github.io/benchhand/contracts/"
PREVIEW_LINE = "docs/design-plan.md:377"
"""The plan's preview-hosting line: `preview.serve(kind, target)`, then `preview.stop` and `preview.list`."""


def _catalogue() -> dict[str, Any]:
    """A small catalogue whose every reference resolves in this repository."""
    return {
        "contract_base": BASE,
        "doc_corrections": [],
        "open_questions": [
            {
                "id": "q",
                "question": "Which?",
                "origin": "existing",
                "pointers": ["docs/design-plan.md:9"],
                "blocking": True,
                "owner": "project-owner",
                "decision_needed": "Which one.",
            }
        ],
        "capabilities": [
            {
                "id": "jobs",
                "title": "Jobs",
                "purpose": "Run jobs.",
                "layer": "core",
                "container": "containers.md:jobService",
                "phase": 1,
                "status": "built",
                "scope": "baseline",
                "evidence": ["packages/benchhand-core/src/benchhand_core/jobs/service.py:119"],
                "owner": ["packages/benchhand-core"],
                "contracts": ["jobs/job.schema.json#/$defs/JobHandle"],
                "prototype": ["skills/cad-flow/scripts/process_lifecycle.py"],
                "adrs": [4],
            },
            {
                "id": "build",
                "title": "Build",
                "purpose": "Build a version.",
                "layer": "providers",
                "container": "containers.md:kernels",
                "phase": 4,
                "status": "planned",
                "scope": "baseline",
                "source": {"kind": "plan", "ref": "docs/design-plan.md:583"},
                "owner": ["providers/kernel-cadquery"],
                "prototype": ["skills/cad-model/scripts/cad_model.py"],
                "depends_on": ["jobs"],
                "open_questions": ["q"],
                "adrs": [7],
            },
        ],
        "tools": [
            {
                "name": "model.build",
                "capability": "build",
                "access": "write",
                "input": "not yet defined",
                "output": "not yet defined",
                "envelope": "sync-or-job",
                "gate": "unspecified",
                "phase": 4,
                "status": "planned",
                "source": {"kind": "plan", "ref": "docs/design-plan.md:363"},
                "replaces": ["cad_model.py run"],
            },
            {
                "name": "jobs.status",
                "capability": "jobs",
                "access": "read",
                "input": "not yet defined",
                "output": "jobs/job.schema.json",
                "envelope": "sync",
                "gate": "none",
                "phase": 3,
                "status": "planned",
                "source": {"kind": "plan", "ref": "docs/design-plan.md:345"},
            },
        ],
        "cli": [
            {
                "name": "record migrate",
                "capability": "jobs",
                "status": "built",
                "evidence": ["packages/benchhand/src/benchhand/cli.py:34"],
                "phase": 1,
                "access": "write",
                "role": "admin",
                "source": {"kind": "code", "ref": "packages/benchhand/src/benchhand/cli.py:33"},
            }
        ],
        "prototype_commands": [
            {
                "command": "cad_model.py run",
                "path": "skills/cad-model/scripts/cad_model.py",
                "capability": "build",
            },
            {
                "command": "process_lifecycle.py strays",
                "path": "skills/cad-flow/scripts/process_lifecycle.py",
                "capability": None,
            },
        ],
    }


def _problems(data: dict[str, Any]) -> list[str]:
    return check_catalogue(Catalogue(data), REPO_ROOT)


def _surface(**fields: Any) -> dict[str, Any]:
    """An MCP surface of the jobs capability, named on the plan's long-jobs line."""
    surface = {
        "resources": ["jobs://"],
        "phase": 3,
        "sources": [{"kind": "plan", "ref": "docs/design-plan.md:345"}],
    }
    return {**surface, "baseline": ["jobs.status"], **fields}


def test_an_mcp_surface_without_a_baseline_tool_must_say_so_and_is_a_gap(tmp_path: Path) -> None:
    data = _catalogue()
    data["capabilities"][0]["mcp"] = _surface(baseline=[])
    path = tmp_path / "capabilities.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(CatalogueError) as raised:
        load_catalogue(path)
    assert "/capabilities/0/mcp: 'baseline_missing' is a required property" in raised.value.problems[0]
    data["capabilities"][0]["mcp"]["baseline_missing"] = "no tool lists the job resources."
    text = render_page(Catalogue(data))
    assert "| `jobs://` | – | – | **missing:** no tool lists the job resources. | P3 |" in text
    assert "### MCP surfaces with a missing baseline (1)\n\n- [jobs](#jobs): no tool lists" in text


def test_a_catalogue_whose_references_resolve_has_no_problems() -> None:
    assert _problems(_catalogue()) == []


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["capabilities"][1]["depends_on"].append("nowhere"), "build depends on nowhere"),
        (
            lambda d: d["tools"][0].update(capability="nowhere"),
            "tool model.build names the capability nowhere",
        ),
        (lambda d: d["tools"][0]["replaces"].append("gone.py"), "replaces the prototype command gone.py"),
        (lambda d: d["capabilities"][1].pop("open_questions"), "open question q is cited by nothing"),
        (lambda d: d["capabilities"][0].update(depends_on=["build"]), "cycle: jobs -> build -> jobs"),
        (
            lambda d: d["capabilities"][0].update(mcp=_surface(baseline=["jobs.list"])),
            "capability jobs names the baseline tool jobs.list",
        ),
        (lambda d: d["tools"].append(copy.deepcopy(d["tools"][1])), "tool jobs.status is listed 2 times"),
        (
            lambda d: d["capabilities"][0].update(no_tool_reason="x"),
            "has tools, so it takes no `no_tool_reason`",
        ),
    ],
)
def test_a_name_that_does_not_resolve_is_reported(change: Any, message: str) -> None:
    data = _catalogue()
    change(data)
    assert any(message in problem for problem in _problems(data)), _problems(data)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda d: d["capabilities"][0].update(evidence=["docs/design-plan.md:99999"]),
            "docs/design-plan.md has",
        ),
        (lambda d: d["capabilities"][0].update(evidence=["docs/nowhere.md"]), "no file docs/nowhere.md"),
        (lambda d: d["capabilities"][0].update(evidence=["../outside.md"]), "stays inside the repository"),
        (
            lambda d: d["tools"][1]["source"].update(ref="docs/design-plan.md:9"),
            "docs/design-plan.md:9 doesn't name jobs.status",
        ),
        (
            lambda d: d["tools"][1].update(
                name="unrelated.list", source={"kind": "plan", "ref": PREVIEW_LINE}
            ),
            f"{PREVIEW_LINE} doesn't name unrelated.list",
        ),
        (
            lambda d: d["capabilities"][0].update(contracts=["jobs/job.schema.json#/$defs/Nothing"]),
            "has no $defs/Nothing",
        ),
        (lambda d: d["tools"][1].update(output="jobs/gone.schema.json"), "is not a published contract"),
        (
            lambda d: d.update(contract_base="https://example.org/contracts/"),
            f"jobs/job.schema.json resolves to https://example.org/contracts/jobs/job.schema.json, "
            f"and the schema's $id is {BASE}jobs/job.schema.json",
        ),
        (lambda d: d["capabilities"][0].update(adrs=[999]), "there is no ADR-0999"),
        (
            lambda d: d["doc_corrections"].append(
                {
                    "pointer": "docs/gone.md:3",
                    "says": "x.",
                    "correction": "y.",
                    "settled_by": ["docs/design-plan.md:9"],
                }
            ),
            "doc correction of docs/gone.md:3: docs/gone.md:3: no file docs/gone.md",
        ),
        (lambda d: d["capabilities"][0].update(container="containers.md:nothing"), "draws no node nothing"),
        (
            lambda d: d["capabilities"][0].update(owner=["packages/gone"]),
            "its owner packages/gone doesn't exist",
        ),
        (
            lambda d: d["capabilities"][1].update(prototype=["skills/cad-x/gone.py"]),
            "skills/cad-x/gone.py is not an entry of docs/architecture/reference-map.yaml",
        ),
        (
            lambda d: d["capabilities"][1].update(prototype=["skills/cad-flow/scripts/run.py"]),
            "capability build doesn't list skills/cad-model/scripts/cad_model.py",
        ),
    ],
)
def test_a_pointer_contract_or_path_that_does_not_resolve_is_reported(change: Any, message: str) -> None:
    data = _catalogue()
    change(data)
    assert any(message in problem for problem in _problems(data)), _problems(data)


@pytest.mark.parametrize(
    ("name", "line", "named"),
    [
        (
            "preview.list",
            "`preview.serve(kind, target)` hosts it. `preview.stop` and `preview.list` manage them.",
            True,
        ),
        (
            "model.section",
            "- **Inspect:** `model.measure`, `section`, `mass_props` and `interference`.",
            True,
        ),
        ("unrelated.list", "`preview.stop` and `preview.list` manage them.", False),
        (
            "unrelated.section",
            "- **Inspect:** `model.measure`, `section`, `mass_props` and `interference`.",
            False,
        ),
        ("model.section", "`section` is cut before `model.measure` runs.", False),
        ("jobs.status", "`jobs.statuses` lists them.", False),
    ],
)
def test_a_tool_source_line_names_the_tool_in_full_or_after_a_sibling_of_its_namespace(
    name: str, line: str, named: bool
) -> None:
    assert tool_named(name, line) is named


@pytest.mark.parametrize(
    ("name", "line", "named"),
    [
        ("record migrate", '@record.command("migrate")', True),
        ("mcp --http", "- `mcp [--http] [--project DIR]` starts the MCP server.", True),
        ("policy set", "- `policy get|set` changes the gate modes and records the DR.", True),
        ("rules compile", "mcp, serve, install, doctor, setup, policy, rules compile and debug call", True),
        ("policy set", "- `policy` changes the gate modes; set them at setup.", False),
        ("debug call", "debug calls", False),
    ],
)
def test_a_cli_source_line_names_the_command_words_in_order(name: str, line: str, named: bool) -> None:
    assert cli_named(name, line) is named


def test_a_schema_violation_is_reported_with_its_path(tmp_path: Path) -> None:
    data = _catalogue()
    data["capabilities"][0]["status"] = "done"
    del data["capabilities"][1]["open_questions"]
    del data["capabilities"][1]["source"]
    data["capabilities"][1]["phase"] = None
    del data["open_questions"][0]["owner"]
    path = tmp_path / "capabilities.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(CatalogueError) as raised:
        load_catalogue(path)
    text = "\n".join(raised.value.problems)
    assert "/capabilities/0/status: 'done' is not one of" in text
    assert "/capabilities/1: 'open_questions' is a required property" in text
    assert "/capabilities/1: 'source' is a required property" in text, (
        "a planned capability cites its plan line"
    )
    assert "/capabilities/1/phase: None is not of type 'integer'" in text, "a baseline capability has a phase"
    assert "/open_questions/0: 'owner' is a required property" in text, "a blocking question has an owner"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda d: d["capabilities"][1]["source"].update(ref="docs/design-plan.md"),
            "capability build is planned, and its source docs/design-plan.md needs a path:LINE",
        ),
        (
            lambda d: d["prototype_commands"][0].update(replaced_without_tool="internal", note="x"),
            "cad_model.py run: a tool replaces it, so it takes no `replaced_without_tool`",
        ),
        (
            lambda d: d["prototype_commands"][1].update(
                capability="build", replaced_without_tool="cli", note="x"
            ),
            "process_lifecycle.py strays: replaced by the CLI, and its capability has no CLI command",
        ),
    ],
)
def test_a_spec_ready_rule_that_fails_is_reported(change: Any, message: str) -> None:
    data = _catalogue()
    change(data)
    assert any(message in problem for problem in _problems(data)), _problems(data)


def _inventory_file(path: str, commands: list[dict[str, Any]], entry: bool = True) -> dict[str, Any]:
    """One file of prototype-inventory.json, with only the keys the coverage check reads."""
    return {"path": path, "entry_points": ["main()"] if entry else [], "commands": commands}


def _parser(words: str, *flags: str, choices: str = "") -> dict[str, Any]:
    options = [{"flags": [flag], "kind": "option", "help": ""} for flag in flags]
    if choices:
        options.append({"flags": ["mode"], "kind": "positional", "help": "check it", "choices": choices})
    return {
        "command": words,
        "framework": "argparse",
        "summary": "",
        "hidden": False,
        "line": 1,
        "options": options,
    }


def _coverage(commands: list[tuple[str, str]], files: list[dict[str, Any]]) -> list[str]:
    data = _catalogue()
    data["prototype_commands"] = [
        {"command": command, "path": path, "capability": "build"} for command, path in commands
    ]
    return check_prototype_commands(Catalogue(data), {"reference_commit": "0" * 40, "files": files})


MOTION = "skills/cad-motion/scripts/motion.py"
STAMP = "skills/cad-recheck/scripts/stamp.py"


def test_a_command_line_the_pin_can_run_needs_an_entry_even_beside_its_sibling() -> None:
    files = [_inventory_file(MOTION, [_parser(""), _parser("plan"), _parser("render")])]
    assert _coverage([("motion.py plan", MOTION)], files) == [
        f"{MOTION}: the pin can run `motion.py render`, and prototype_commands has no entry for it"
    ]


def test_a_matching_string_that_is_not_a_command_line_does_not_pass() -> None:
    """`check` is a choice and a help word of motion.py's parser, which the old text search accepted."""
    files = [_inventory_file(MOTION, [_parser("", choices="('check', 'plan')"), _parser("plan")])]
    assert _coverage([("motion.py plan", MOTION), ("motion.py check", MOTION)], files) == [
        f"prototype command motion.py check: {MOTION} has no command line `check` at the pin"
    ]


def test_a_flag_only_mode_needs_its_flags_and_does_not_stand_for_the_command_line() -> None:
    files = [_inventory_file(STAMP, [_parser("", "--verify", "--committed")])]
    assert _coverage([("stamp.py --verify --committed", STAMP), ("stamp.py --diff", STAMP)], files) == [
        f"{STAMP}: the pin can run `stamp.py`, and prototype_commands has no entry for it",
        "prototype command stamp.py --diff: `stamp.py` declares no --diff at the pin",
    ]


def test_a_runnable_script_without_a_parser_is_one_command_line_and_tests_are_left_out() -> None:
    runner = "skills/cad-flow/scripts/run.py"
    files = [
        _inventory_file(runner, []),
        _inventory_file("skills/cad-flow/scripts/lib.py", [], entry=False),
        _inventory_file("skills/cad-flow/scripts/test_run.py", []),
        _inventory_file("harness/generate.py", [_parser("", "--check")]),
    ]
    assert _coverage([("run.py", runner), ("gen.py", "harness/generate.py")], files) == [
        "harness/generate.py: the pin can run `generate.py`, and prototype_commands has no entry for it",
        "prototype command gen.py: names gen.py, and its path is harness/generate.py",
    ]


def test_the_graph_draws_solid_only_between_capabilities_on_main_and_labels_every_phase() -> None:
    data = _catalogue()
    data["capabilities"].append(
        {**copy.deepcopy(data["capabilities"][0]), "id": "store", "depends_on": ["jobs"]}
    )
    text = render_page(Catalogue(data))
    graph = text.split("```mermaid\n")[1].split("\n```")[0]
    assert "  build -.-> jobs" in graph
    assert "  store --> jobs" in graph
    assert 'build["Build<br/>P4, planned"]:::planned' in graph
    assert "| **all** | **3** | 2 | 0 | 1 | 0 | 0 |" in text


def test_a_dashed_arrow_to_a_proposed_or_phaseless_capability_says_which() -> None:
    data = _catalogue()
    data["capabilities"] += [
        {
            **copy.deepcopy(data["capabilities"][1]),
            "id": "docs",
            "status": "proposed",
            "depends_on": ["jobs"],
        },
        {**copy.deepcopy(data["capabilities"][1]), "id": "host", "phase": None, "depends_on": ["jobs"]},
    ]
    graph = render_page(Catalogue(data)).split("```mermaid\n")[1]
    assert "  docs -.->|proposed| jobs" in graph
    assert "  host -.->|no phase| jobs" in graph


def test_the_gap_list_splits_missing_interfaces_intentional_replacements_and_proposals() -> None:
    data = _catalogue()
    data["tools"] = data["tools"][:1]
    data["tools"].append(
        {
            **copy.deepcopy(data["tools"][0]),
            "name": "model.check",
            "status": "dropped",
            "note": "Gone at the pin.",
        }
    )
    del data["tools"][1]["replaces"]
    data["prototype_commands"][1].update(
        capability="jobs", replaced_without_tool="cli", note="`record migrate`."
    )
    text = render_page(Catalogue(data))
    gaps = text.split("## Gaps")[1].split("## Open questions")[0]
    missing, intentional, proposals = (part.split("\n### ")[0] for part in gaps.split("\n### ")[1:4])
    assert missing.startswith("Missing interfaces (2)")
    assert "#### Capabilities with no MCP tool (1)\n\n- [jobs](#jobs) (P1, built)" in missing
    assert "- `model.build`: input and output" in missing
    assert "model.check" not in missing, "a dropped tool needs no contract"
    assert intentional.startswith("Intentional CLI or internal replacements (1)")
    assert "- `process_lifecycle.py strays` ([jobs](#jobs)): `record migrate`." in intentional
    assert "#### Dropped tools (1)\n\n- `model.check` ([build](#build), plan): Gone at the pin." in proposals


def test_the_committed_catalogue_is_valid_and_its_page_is_current() -> None:
    """The file, its references, its prototype commands against the committed inventory, and the page."""
    assert "prototype commands checked against docs/architecture/prototype-inventory.json" in run(
        REPO_ROOT, write=False
    )


@needs_mermaid
def test_the_dependency_graph_renders(tmp_path: Path) -> None:
    text = (REPO_ROOT / OUTPUT_FILE).read_text(encoding="utf-8")
    assert mermaid_blocks(text) == 1
    assert len(render_markdown(text, tmp_path)) == 1


def test_the_catalogue_and_its_page_are_where_the_justfile_expects() -> None:
    assert (REPO_ROOT / CATALOGUE_FILE).is_file()
    assert (REPO_ROOT / OUTPUT_FILE).is_file()
