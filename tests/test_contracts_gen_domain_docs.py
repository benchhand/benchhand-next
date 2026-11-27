# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The domain model's pages: every type is described, every link resolves, and the committed tree is current."""

from __future__ import annotations

import os
import posixpath
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from contracts_gen.domain import MAX_ENUM_VALUES, DomainModel, build_model, class_id, ref_counts
from contracts_gen.domain_d2 import (
    D2_COMMAND,
    MAX_DIAGRAM_NODES,
    overview_rows,
    plan_diagrams,
    relationship_rows,
)
from contracts_gen.domain_docs import (
    MODEL_DIR,
    README_PATH,
    STUB_FILE,
    diagram_sources,
    domain_model_files,
    write_domain_model,
)
from contracts_gen.sources import DOCS_OUT, REPO_ROOT, SCHEMAS_OUT, Contract, load_contracts

IN_CI = os.environ.get("CI") == "true"
needs_d2 = pytest.mark.skipif(
    shutil.which(D2_COMMAND) is None and not IN_CI, reason="needs d2 on PATH (`mise install`)"
)

_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")
_TYPE_HEADING = re.compile(r"^### `([^`]+)`", re.MULTILINE)
_TABLE = re.compile(r'^\s*"[^"]+": \{\n\s*class: (?:document|owned|union)', re.MULTILINE)


def _contract(stem: str, schema: dict[str, Any]) -> Contract:
    return Contract(f"{stem}.schema.json", {"$id": f"https://example.test/{stem}", **schema})


SHOP = _contract(
    "record/shop",
    {
        "type": "object",
        "description": "A shop.",
        "required": ["kind", "size"],
        "properties": {
            "kind": {"enum": ["big", "small"], "description": "How a shop is sized | by floor area."},
            "size": {"enum": [f"s{n}" for n in range(MAX_ENUM_VALUES + 1)], "description": "The size."},
            "tags": {"$ref": "#/$defs/tag"},
            "door": {"$ref": "#/$defs/door"},
        },
        "$defs": {
            "tag": {"enum": ["a", "b"], "description": "A label."},
            "door": {"type": "object", "properties": {"width": {"type": "number"}}},
        },
    },
)

LIBRARY = _contract("record/library", {"$defs": {"colour": {"enum": ["red", "green"]}}})


@pytest.fixture(scope="module")
def published() -> tuple[list[Contract], DomainModel, dict[str, str]]:
    contracts = load_contracts(REPO_ROOT / SCHEMAS_OUT)
    return contracts, build_model(contracts), domain_model_files(contracts)


def _page(stem: str) -> str:
    return f"{MODEL_DIR}/{stem}.md"


def test_every_class_has_a_heading_and_a_table_in_its_contract_page_and_a_diagram(
    published: tuple[list[Contract], DomainModel, dict[str, str]],
) -> None:
    _, model, files = published
    plan = plan_diagrams(model)
    headings = {
        stem: Counter(_TYPE_HEADING.findall(files[_page(stem)].split("## Types", 1)[1].split("## Enums")[0]))
        for stem in plan.diagrams
    }
    for stem, diagrams in plan.diagrams.items():
        expected = Counter(node.label for node in model.classes.values() if node.stem == stem)
        assert headings[stem] == expected, stem
        in_diagrams = [member for diagram in diagrams for member in diagram.owned]
        assert sorted(in_diagrams) == sorted(node.id for node in model.classes.values() if node.stem == stem)
    assert sum(sum(found.values()) for found in headings.values()) == len(model.classes)


def test_every_published_root_is_drawn_and_described(
    published: tuple[list[Contract], DomainModel, dict[str, str]],
) -> None:
    _, model, files = published
    plan = plan_diagrams(model)
    assert model.document_stems
    for stem in model.document_stems:
        assert class_id(stem, None) in plan.home, stem
        assert f"### `{stem.rsplit('/', 1)[-1]}`" in files[_page(stem)], stem


def test_every_diagram_owns_at_most_the_node_limit(
    published: tuple[list[Contract], DomainModel, dict[str, str]],
) -> None:
    _, _, files = published
    sources = diagram_sources(files)
    assert sources
    for path in sources:
        if path == f"{MODEL_DIR}/overview.d2":
            continue
        assert 1 <= len(_TABLE.findall(files[path])) <= MAX_DIAGRAM_NODES, path


def test_the_readme_indexes_every_contract_and_shows_the_overview(
    published: tuple[list[Contract], DomainModel, dict[str, str]],
) -> None:
    contracts, _, files = published
    readme = files[README_PATH]
    for contract in contracts:
        assert f"| [`{contract.stem}`]({contract.stem}.md) |" in readme
        assert f"{MODEL_DIR}/{contract.stem}.md" in files
    assert "](overview.svg)" in readme
    assert "**Enums have no colour.**" in readme


def test_every_diagram_is_followed_by_a_table_of_its_relationships(
    published: tuple[list[Contract], DomainModel, dict[str, str]],
) -> None:
    """A diagram's text alternative (WCAG 1.1.1): one row for each arrow it draws."""
    _, model, files = published
    plan = plan_diagrams(model)
    tables = 0
    for stem, diagrams in plan.diagrams.items():
        page = files[_page(stem)]
        for diagram in diagrams:
            section = page.split(f"### {diagram.number}. `{diagram.title}`", 1)[1].split("\n### ", 1)[0]
            assert section.lstrip().startswith(f"![Diagram {diagram.number} of {stem}"), stem
            rows = relationship_rows(model, diagram)
            if not rows:
                assert f"Diagram {diagram.number} has no relationships." in section
                continue
            assert f"Relationships in diagram {diagram.number}:" in section
            table = [line for line in section.splitlines() if line.startswith("| ") and " | " in line]
            assert table[0] == "| Source | Relation | Target | Cardinality |"
            assert len(table) == len(rows) + 1, f"{stem} diagram {diagram.number}"  # the header and a row each
            tables += 1
    assert tables > 20


def test_the_readme_lists_each_arrow_of_the_overview_in_a_table() -> None:
    contracts = load_contracts(REPO_ROOT / SCHEMAS_OUT)
    readme = domain_model_files(contracts)[README_PATH]
    section = readme.split("### Relationships in the overview", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| ")]
    assert rows[0] == "| Source | Relation | Target | Cardinality |"
    assert len(rows) - 1 == len(overview_rows(build_model(contracts), ref_counts(contracts)))
    assert "| assembly | references | common (library) | 31 refs |" in rows


def test_every_committed_svg_has_a_title_and_a_description() -> None:
    root = REPO_ROOT / DOCS_OUT / MODEL_DIR
    svgs = sorted(root.rglob("*.svg"))
    assert len(svgs) > 40
    for svg in svgs:
        text = svg.read_text(encoding="utf-8")
        assert 'role="img" aria-labelledby="diagram-title diagram-desc"' in text, svg.name
        assert re.search(
            r'<title id="diagram-title">[^<]+</title><desc id="diagram-desc">[^<]+</desc>', text
        ), svg.name


def test_the_old_page_is_a_stub_that_links_to_the_readme(
    published: tuple[list[Contract], DomainModel, dict[str, str]],
) -> None:
    _, _, files = published
    assert _LINK.findall(files[STUB_FILE]) == [README_PATH]


def _exists(rel_path: str, link: str, files: dict[str, str]) -> bool:
    """Whether ``link``, read in the generated file ``rel_path``, points at a file that is or will be there."""
    target = posixpath.normpath(posixpath.join(DOCS_OUT, posixpath.dirname(rel_path), link.split("#")[0]))
    generated = {f"{DOCS_OUT}/{path}" for path in files}
    svg_sources = {path.removesuffix(".d2") + ".svg" for path in generated if path.endswith(".d2")}
    return target in generated or target in svg_sources or (REPO_ROOT / target).is_file()


def test_every_link_and_image_of_the_pages_resolves(
    published: tuple[list[Contract], DomainModel, dict[str, str]],
) -> None:
    _, _, files = published
    checked = 0
    for rel_path, text in files.items():
        if not rel_path.endswith(".md"):
            continue
        for link in _LINK.findall(text):
            assert _exists(rel_path, link, files), f"{rel_path}: {link}"
            checked += 1
    assert checked > 100


def test_every_stub_links_to_a_diagram_that_exists(
    published: tuple[list[Contract], DomainModel, dict[str, str]],
) -> None:
    _, _, files = published
    stubs = 0
    for rel_path in diagram_sources(files):
        for link in re.findall(r'^\s*link: "([^"]+)"$', files[rel_path], re.MULTILINE):
            assert _exists(rel_path, link, files), f"{rel_path}: {link}"
            assert link.endswith(".svg")
            stubs += 1
    assert stubs > 0


def test_every_named_enum_is_in_the_enum_table_of_its_page(
    published: tuple[list[Contract], DomainModel, dict[str, str]],
) -> None:
    contracts, _, files = published
    named = 0
    for contract in contracts:
        enums = [name for name, schema in contract.schema.get("$defs", {}).items() if "enum" in schema]
        for name in enums:
            table = files[_page(contract.stem)].split("## Enums", 1)[1]
            assert f"| `{name}` |" in table, f"{contract.stem}: {name}"
            named += 1
    assert named > 0


def test_a_page_has_a_field_table_with_required_and_description_and_an_enum_table() -> None:
    files = domain_model_files([SHOP, LIBRARY])
    page = files[_page("record/shop")]
    assert "| Field | Type | Required | Description |" in page
    assert r"| `kind` | `enum big\|small` | yes | How a shop is sized \| by floor area. |" in page
    assert "| `tags` | `tag = a\\|b` | no |  |" in page
    assert "| `width` | `number` | no |  |" in page
    assert "### `shop.door`" not in page  # a $ref'd type keeps its own name
    enums = page.split("## Enums", 1)[1]
    assert "| `tag` | `a`, `b` | A label. |" in enums
    assert "| `shop.size` | `s0`, `s1`, `s2`, `s3`, `s4`, `s5`, `s6` | The size. |" in enums
    assert "`kind`" not in enums  # short enums are spelled out in the field's type
    assert "| `colour` | `red`, `green` |  |" in files[_page("record/library")]


def test_a_contract_without_a_type_gets_a_page_with_its_enums_only() -> None:
    page = domain_model_files([SHOP, LIBRARY])[_page("record/library")]
    assert "no types" in page
    assert "## Diagrams" not in page
    assert "## Enums" in page


def test_a_description_already_shown_is_not_repeated_under_the_type() -> None:
    page = domain_model_files([SHOP])[_page("record/shop")]
    assert page.count("A shop.") == 1


@needs_d2
def test_writing_lays_every_diagram_out_beside_its_source(tmp_path: Path) -> None:
    write_domain_model([SHOP, LIBRARY], tmp_path)
    sources = list((tmp_path / MODEL_DIR).rglob("*.d2"))
    assert {path.name for path in sources} >= {"classes.d2", "overview.d2", "01-shop.d2"}
    for source in sources:
        if source.name != "classes.d2":
            assert b"<svg" in source.with_suffix(".svg").read_bytes()
    assert (tmp_path / STUB_FILE).is_file()


def test_the_committed_pages_and_sources_are_what_the_generator_writes(
    published: tuple[list[Contract], DomainModel, dict[str, str]],
) -> None:
    """The drift check covers every generated file, the SVGs byte for byte; this one names what a reader opens."""
    _, _, files = published
    root = REPO_ROOT / DOCS_OUT
    for rel_path, text in files.items():
        assert (root / rel_path).read_text(encoding="utf-8") == text, rel_path
    for source in diagram_sources(files):
        assert (root / source).with_suffix(".svg").read_bytes().lstrip().startswith(b"<?xml"), source
    committed = {
        path.relative_to(root).as_posix()
        for path in (root / MODEL_DIR).rglob("*")
        if path.is_file() and path.suffix in {".md", ".d2", ".svg"}
    }
    expected = set(files) - {STUB_FILE}
    expected |= {path.removesuffix(".d2") + ".svg" for path in diagram_sources(files)}
    assert committed == expected


def test_every_rendered_svg_keeps_the_links_of_its_source_and_each_resolves(
    published: tuple[list[Contract], DomainModel, dict[str, str]],
) -> None:
    """D2 drops a link it doesn't read as a URL, so the committed SVGs are read, not the sources alone."""
    _, _, files = published
    root = REPO_ROOT / DOCS_OUT
    linked = 0
    for source in diagram_sources(files):
        links = set(re.findall(r'^\s*link: "([^"]+)"$', files[source], re.MULTILINE))
        svg = (root / source).with_suffix(".svg").read_text(encoding="utf-8")
        hrefs = set(re.findall(r'href="([^"]+)"', svg))
        assert hrefs == links, source
        for href in hrefs:
            target = posixpath.normpath(posixpath.join(posixpath.dirname(source), href))
            assert (root / target).is_file(), f"{source}: {href}"
        linked += len(hrefs)
    assert linked > 50
    assert 'href="./' in (root / MODEL_DIR / "overview.svg").read_text(encoding="utf-8")
