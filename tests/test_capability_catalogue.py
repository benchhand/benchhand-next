# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""tools/catalogue: the capability catalogue's checks, its coverage of the prototype, and its page."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from capability_catalogue.catalogue import Catalogue, CatalogueError, load_catalogue
from capability_catalogue.checks import check_catalogue
from capability_catalogue.cli import CATALOGUE_FILE, OUTPUT_FILE, REFERENCE_ENV, REPO_ROOT, run
from capability_catalogue.coverage import check_prototype_commands
from capability_catalogue.render import render_page
from mermaid_render import mermaid_blocks, needs_mermaid, render_markdown

BASE = "https://benchhand.github.io/benchhand/contracts/"


def _catalogue() -> dict[str, Any]:
    """A small catalogue whose every reference resolves in this repository."""
    return {
        "contract_base": BASE,
        "open_questions": [
            {"id": "q", "question": "Which?", "origin": "existing", "pointers": ["docs/design-plan.md:9"]}
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
            "docs/design-plan.md:9 doesn't name status",
        ),
        (
            lambda d: d["capabilities"][0].update(contracts=["jobs/job.schema.json#/$defs/Nothing"]),
            "has no $defs/Nothing",
        ),
        (lambda d: d["tools"][1].update(output="jobs/gone.schema.json"), "is not a published contract"),
        (lambda d: d["capabilities"][0].update(adrs=[999]), "there is no ADR-0999"),
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


def test_a_schema_violation_is_reported_with_its_path(tmp_path: Path) -> None:
    data = _catalogue()
    data["capabilities"][0]["status"] = "done"
    del data["capabilities"][1]["open_questions"]
    data["capabilities"][1]["phase"] = None
    path = tmp_path / "capabilities.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(CatalogueError) as raised:
        load_catalogue(path)
    text = "\n".join(raised.value.problems)
    assert "/capabilities/0/status: 'done' is not one of" in text
    assert "/capabilities/1: 'open_questions' is a required property" in text


def test_a_runnable_prototype_script_needs_a_command_and_its_subcommand_must_exist(tmp_path: Path) -> None:
    scripts = tmp_path / "skills" / "cad-model" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "cad_model.py").write_text('sub.add_parser("check")\nif __name__ == "__main__": main()\n')
    (scripts / "lib.py").write_text("def helper(): ...\n")
    (scripts / "test_cad_model.py").write_text('if __name__ == "__main__": main()\n')
    (tmp_path / "skills" / "cad-flow" / "scripts").mkdir(parents=True)
    (tmp_path / "skills" / "cad-flow" / "scripts" / "extra.py").write_text(
        'if __name__ == "__main__": go()\n'
    )
    data = _catalogue()
    data["prototype_commands"] = data["prototype_commands"][:1]
    assert check_prototype_commands(Catalogue(data), tmp_path) == [
        "skills/cad-flow/scripts/extra.py is a runnable prototype script with no entry in prototype_commands",
        "prototype command cad_model.py run: skills/cad-model/scripts/cad_model.py declares no run",
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


def test_the_gap_list_names_toolless_capabilities_undefined_contracts_and_unowned_commands() -> None:
    data = _catalogue()
    data["tools"] = data["tools"][:1]
    text = render_page(Catalogue(data))
    gaps = text.split("## Gaps")[1].split("## Open questions")[0]
    assert "### Capabilities with no MCP tool (1)\n\n- [jobs](#jobs) (P1, built)" in gaps
    assert "- `model.build`: input and output" in gaps
    assert "### Prototype commands with no capability (1)\n\n- `process_lifecycle.py strays`" in gaps


def test_the_committed_catalogue_is_valid_and_its_page_is_current() -> None:
    """Without a reference copy this checks the file, its references and the committed page."""
    assert "prototype commands not checked" in run(REPO_ROOT, None, write=False)


def test_every_runnable_prototype_script_has_a_command() -> None:
    """Mandatory in CI, which fetches the pinned copy; skipped locally without one."""
    if REFERENCE_ENV not in os.environ:
        if os.environ.get("CI") == "true":
            pytest.fail(f"CI=true needs a prototype copy in ${REFERENCE_ENV}")
        pytest.skip(f"needs a prototype copy in ${REFERENCE_ENV}")
    assert "prototype commands checked against" in run(
        REPO_ROOT, Path(os.environ[REFERENCE_ENV]), write=False
    )


@needs_mermaid
def test_the_dependency_graph_renders(tmp_path: Path) -> None:
    text = (REPO_ROOT / OUTPUT_FILE).read_text(encoding="utf-8")
    assert mermaid_blocks(text) == 1
    assert len(render_markdown(text, tmp_path)) == 1


def test_the_catalogue_and_its_page_are_where_the_justfile_expects() -> None:
    assert (REPO_ROOT / CATALOGUE_FILE).is_file()
    assert (REPO_ROOT / OUTPUT_FILE).is_file()
