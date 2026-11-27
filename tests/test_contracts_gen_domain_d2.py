# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The D2 renderer of the domain model: aggregates, the size limit, stubs and links, and the D2 version pin."""

from __future__ import annotations

import os
import posixpath
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
from contracts_gen.domain import ClassNode, DomainModel, build_model, ref_counts
from contracts_gen.domain_d2 import (
    CLASSES_D2,
    D2_COMMAND,
    D2_LAYOUT,
    D2_VERSION,
    MAX_DIAGRAM_NODES,
    MAX_TYPE_CHARS,
    Caption,
    D2VersionError,
    add_caption,
    check_d2_version,
    diagram_caption,
    overview_caption,
    overview_rows,
    parse_d2_version,
    plan_diagrams,
    relationship_rows,
    render_d2,
    render_diagram,
    render_env,
    render_overview,
    shown_relations,
    stubs_of,
    svg_link,
)
from contracts_gen.sources import REPO_ROOT, SCHEMAS_OUT, Contract, load_contracts

IN_CI = os.environ.get("CI") == "true"
needs_d2 = pytest.mark.skipif(
    shutil.which(D2_COMMAND) is None and not IN_CI, reason="needs d2 on PATH (`mise install`)"
)
"""Skip a render test locally when d2 is missing; in CI it runs, and fails without it."""


def _contract(stem: str, schema: dict[str, Any]) -> Contract:
    return Contract(f"{stem}.schema.json", {"$id": f"https://example.test/{stem}", **schema})


def _object(*names: str, **refs: str) -> dict[str, Any]:
    properties: dict[str, Any] = {name: {"type": "string"} for name in names}
    properties.update({name: {"$ref": ref} for name, ref in refs.items()})
    return {"type": "object", "required": list(properties)[:1], "properties": properties}


PERSON = _contract("common/person", {"$defs": {"name": _object("first", "last")}})

SHOP = _contract(
    "record/shop",
    {
        "type": "object",
        "required": ["owner", "stock"],
        "properties": {
            "owner": {"$ref": "../common/person.schema.json#/$defs/name"},
            "stock": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/shelf"}},
            "front": {"$ref": "#/$defs/door"},
            "back": {"$ref": "#/$defs/door"},
        },
        "$defs": {
            "shelf": _object("label", item="#/$defs/item", lock="#/$defs/lock"),
            "item": _object("sku"),
            "door": _object("width", lock="#/$defs/lock"),
            "lock": _object("code"),
            "annex": _object("name", lock="#/$defs/lock"),
        },
    },
)


def _flat_union(count: int) -> Contract:
    branches = {
        f"b{n}": {**_object("kind", "n"), "properties": {"kind": {"const": f"b{n}"}}} for n in range(count)
    }
    return _contract(
        "record/wide",
        {
            "type": "object",
            "required": ["item"],
            "properties": {"item": {"$ref": "#/$defs/item"}},
            "$defs": {**branches, "item": {"oneOf": [{"$ref": f"#/$defs/{name}"} for name in branches]}},
        },
    )


def _model(*contracts: Contract) -> DomainModel:
    return build_model(list(contracts))


def _published() -> list[Contract]:
    return load_contracts(REPO_ROOT / SCHEMAS_OUT)


def _aggregate_of(plan_diagrams_: Any, class_: str) -> tuple[str, ...]:
    """The members of the aggregate that holds ``class_``."""
    for diagrams in plan_diagrams_.diagrams.values():
        for diagram in diagrams:
            for aggregate in diagram.aggregates:
                if class_ in aggregate.members:
                    return aggregate.members
    raise AssertionError(class_)


def test_an_aggregate_is_a_root_with_the_types_only_it_owns() -> None:
    model = _model(PERSON, SHOP)
    plan = plan_diagrams(model)
    shop = _aggregate_of(plan, "record_shop")
    assert "record_shop__owner" not in shop  # a type of another contract is not owned
    assert "record_shop__shelf" in shop
    assert "record_shop__item" in shop  # held by the shelf only
    assert "record_shop__door" in shop  # held by the shop twice: still only the shop
    assert "record_shop__annex" not in shop  # held by nothing, so a root


def test_a_type_held_from_two_aggregates_roots_one_of_its_own() -> None:
    model = _model(PERSON, SHOP)
    plan = plan_diagrams(model)
    lock = _aggregate_of(plan, "record_shop__lock")
    assert lock == ("record_shop__lock",)  # held by the shelf, the door and the annex
    assert "record_shop__lock" not in _aggregate_of(plan, "record_shop__shelf")
    assert "record_shop__lock" not in _aggregate_of(plan, "record_shop__annex")


def test_every_class_is_owned_by_exactly_one_diagram() -> None:
    model = _model(PERSON, SHOP, _flat_union(30))
    plan = plan_diagrams(model)
    owned = [
        member for diagrams in plan.diagrams.values() for diagram in diagrams for member in diagram.owned
    ]
    assert sorted(owned) == sorted(model.classes)


def test_a_wide_aggregate_is_split_so_that_no_diagram_exceeds_the_limit() -> None:
    model = _model(_flat_union(30))
    plan = plan_diagrams(model)
    sizes = [len(diagram.owned) for diagram in plan.diagrams["record/wide"]]
    assert len(model.classes) > MAX_DIAGRAM_NODES
    assert len(sizes) > 1
    assert max(sizes) <= MAX_DIAGRAM_NODES


def test_a_deep_aggregate_sheds_whole_subtrees() -> None:
    chain = {f"n{n}": _object("x", next=f"#/$defs/n{n + 1}") for n in range(20)}
    chain["n20"] = _object("x")
    model = _model(
        _contract(
            "record/chain",
            {"type": "object", "properties": {"head": {"$ref": "#/$defs/n0"}}, "$defs": chain},
        )
    )
    plan = plan_diagrams(model)
    assert max(len(d.owned) for d in plan.diagrams["record/chain"]) <= MAX_DIAGRAM_NODES
    assert sum(len(d.owned) for d in plan.diagrams["record/chain"]) == len(model.classes)


def test_the_published_contracts_split_into_diagrams_within_the_limit() -> None:
    model = build_model(_published())
    plan = plan_diagrams(model)
    for stem, diagrams in plan.diagrams.items():
        for diagram in diagrams:
            assert 1 <= len(diagram.owned) <= MAX_DIAGRAM_NODES, f"{diagram.path} in {stem}"
    assert len(plan.home) == len(model.classes)


def test_every_class_of_the_published_model_is_drawn_as_a_table_in_its_diagram() -> None:
    model = build_model(_published())
    plan = plan_diagrams(model)
    drawn: set[str] = set()
    for diagrams in plan.diagrams.values():
        for diagram in diagrams:
            source = render_diagram(model, plan, diagram)
            tables = re.findall(
                r'^\s*"([^"]+)": \{\n\s*class: (?:document|owned|union)', source, re.MULTILINE
            )
            assert sorted(tables) == sorted(diagram.owned)
            drawn.update(tables)
    assert drawn == set(model.classes)


def test_a_table_has_a_row_per_field_with_a_required_marker() -> None:
    model = _model(PERSON, SHOP)
    plan = plan_diagrams(model)
    shop = plan.home["record_shop"]
    source = render_diagram(model, plan, shop)
    assert '"owner": "name" { constraint: "req" }' in source
    assert '"stock": "shelf[1..*]" { constraint: "req" }' in source
    assert '"front": "door"\n' in source


def test_an_edge_carries_the_field_name_and_the_cardinality() -> None:
    model = _model(PERSON, SHOP)
    plan = plan_diagrams(model)
    source = render_diagram(model, plan, plan.home["record_shop"])
    assert re.search(r'"stock"\s*->\s*\S+: "stock \[1\.\.\*\]"', source)
    assert '"owner [1]"' in source
    assert "front, back [0..1]" in source  # two optional fields to one door: one edge, one cardinality


def test_a_stub_is_a_grey_name_only_node_that_links_to_the_diagram_of_its_class() -> None:
    model = _model(PERSON, SHOP)
    plan = plan_diagrams(model)
    shop = plan.home["record_shop"]
    stubs = stubs_of(model, shop)
    assert "common_person__name" in stubs
    source = render_diagram(model, plan, shop)
    person = plan.home["common_person__name"]
    assert 'class: stub\n  label: "name\\n(common/person)"\n  link: "../../' + person.path + '.svg"' in source


def test_every_stub_of_the_published_diagrams_links_to_a_diagram_that_exists() -> None:
    model = build_model(_published())
    plan = plan_diagrams(model)
    paths = {diagram.path for diagrams in plan.diagrams.values() for diagram in diagrams}
    stubs = 0
    for diagrams in plan.diagrams.values():
        for diagram in diagrams:
            source = render_diagram(model, plan, diagram)
            links = re.findall(r'^  link: "([^"]+)"$', source, re.MULTILINE)
            assert len(links) == len(stubs_of(model, diagram))
            for link in links:
                target = posixpath.normpath(posixpath.join(posixpath.dirname(diagram.path), link))
                assert target.removesuffix(".svg") in paths, f"{diagram.path} links to {link}"
                stubs += 1
    assert stubs > 0


def test_a_stub_of_a_class_in_another_diagram_of_the_same_contract_names_only_the_class() -> None:
    model = _model(_flat_union(30))
    plan = plan_diagrams(model)
    diagram = plan.home["record_wide__item"]
    stubs = stubs_of(model, diagram)
    assert stubs
    source = render_diagram(model, plan, diagram)
    for stub in stubs:
        assert plan.home[stub] is not diagram
        assert f'label: "{model.classes[stub].label}"\n  link: "./{plan.home[stub].number:02d}-' in source


def test_the_overview_has_documents_and_libraries_and_counts_refs_without_fields() -> None:
    contracts = _published()
    model = build_model(contracts)
    plan = plan_diagrams(model)
    source = render_overview(model, plan, ref_counts(contracts))
    assert "class: overview_document" in source
    assert "class: overview_library" in source
    assert "sql_table" not in source
    assert re.search(r'-> "record/[^"]+": "\d+ refs"', source)
    for link in re.findall(r'link: "([^"]+)"', source):
        assert link.startswith("./")
        assert posixpath.normpath(link).removesuffix(".svg") in {
            d.path for ds in plan.diagrams.values() for d in ds
        }


def test_the_colours_are_set_once_in_a_shared_class_file() -> None:
    for name in ("document", "owned", "union", "stub", "aggregate"):
        assert f"\n  {name}: " in CLASSES_D2
    model = _model(PERSON, SHOP)
    plan = plan_diagrams(model)
    assert "fill:" not in render_diagram(model, plan, plan.home["record_shop"])


def test_a_class_with_a_stereotype_is_drawn_as_a_union() -> None:
    model = _model(_flat_union(3))
    node: ClassNode = model.classes["record_wide__item"]
    plan = plan_diagrams(model)
    source = render_diagram(model, plan, plan.home[node.id])
    assert f'label: "{node.label}  «{node.stereotype}»"' in source
    assert "class: union" in source


def test_a_table_header_names_its_type_so_that_colour_is_not_the_only_cue() -> None:
    model = _model(PERSON, SHOP)
    plan = plan_diagrams(model)
    source = render_diagram(model, plan, plan.home["record_shop"])
    assert 'label: "shop  \u00abdocument\u00bb"' in source
    assert 'label: "shelf  \u00abtype\u00bb"' in source
    wide = _model(_flat_union(3))
    wide_plan = plan_diagrams(wide)
    assert '  \u00ababstract\u00bb"' in render_diagram(wide, wide_plan, wide_plan.home["record_wide__item"])
    tables = re.findall(r'label: "[^"]+  \u00ab(\w+)\u00bb"', source)
    assert tables and set(tables) <= {"document", "type", "union", "abstract"}


def test_the_overview_tells_a_document_from_a_library_by_shape_as_well_as_colour() -> None:
    assert "overview_document: {\n    shape: page" in CLASSES_D2
    assert "overview_library: {\n    shape: package" in CLASSES_D2


def test_every_arrow_of_a_diagram_is_a_relationship_row() -> None:
    model = _model(PERSON, SHOP)
    plan = plan_diagrams(model)
    shop = plan.home["record_shop"]
    rows = relationship_rows(model, shop)
    assert [row.source for row in rows if row.target == "name (common/person)"] == ["shop"]
    stock = next(row for row in rows if row.relation == "composition via `stock`")
    assert (stock.source, stock.target, stock.cardinality) == ("shop", "shelf", "1..*")
    drawn = shown_relations(model, set(shop.owned))
    assert len(rows) == len(drawn)
    assert {row.cardinality for row in rows} <= {"1", "1..*", "0..1", "0..*"}


def test_the_published_diagrams_list_as_many_relationships_as_they_draw() -> None:
    model = build_model(_published())
    plan = plan_diagrams(model)
    total = 0
    for diagrams in plan.diagrams.values():
        for diagram in diagrams:
            rows = relationship_rows(model, diagram)
            assert len(rows) == len(shown_relations(model, set(diagram.owned))), diagram.path
            assert all(all(cell for cell in vars(row).values()) for row in rows), diagram.path
            total += len(rows)
    assert total > 100


def test_an_inheritance_row_says_which_end_is_the_parent_and_has_no_cardinality() -> None:
    model = _model(_flat_union(3))
    plan = plan_diagrams(model)
    rows = relationship_rows(model, plan.home["record_wide__item"])
    inheritance = [row for row in rows if row.relation.startswith("inheritance")]
    assert len(inheritance) == 3
    assert all(row.source == "item" and row.cardinality == "\u2014" for row in inheritance)


def test_the_overview_lists_every_arrow_it_draws() -> None:
    contracts = _published()
    model = build_model(contracts)
    plan = plan_diagrams(model)
    refs = ref_counts(contracts)
    rows = overview_rows(model, refs)
    source = render_overview(model, plan, refs)
    assert len(rows) == len(re.findall(r"^\S.* -> ", source, re.MULTILINE)) == 27
    assert any(row.target.endswith("(library)") for row in rows)
    assert all(re.fullmatch(r"\d+ refs?", row.cardinality) for row in rows)
    assert len(re.findall(r'"1 ref"', source)) == sum(1 for row in rows if row.cardinality == "1 ref")


def test_a_caption_names_the_diagram_and_spells_out_its_arrows() -> None:
    model = _model(PERSON, SHOP)
    plan = plan_diagrams(model)
    caption = diagram_caption(model, plan.home["record_shop"])
    assert caption.title == "record/shop, diagram 1: shop"
    assert "Types: shop, shelf, item, door" in caption.description
    assert "shop to shelf: composition via stock, 1..*" in caption.description
    contracts = [PERSON, SHOP]
    overview = overview_caption(model, ref_counts(contracts))
    assert overview.title and "documents" in overview.description


def test_a_caption_goes_into_the_outermost_svg_as_role_title_and_desc() -> None:
    svg = b'<?xml version="1.0"?><svg xmlns="x" viewBox="0 0 1 1"><svg class="d2" width="1"></svg></svg>'
    out = add_caption(svg, Caption("A & B", "x < y")).decode()
    assert out.startswith(
        '<?xml version="1.0"?><svg xmlns="x" viewBox="0 0 1 1" role="img" aria-labelledby="'
    )
    assert (
        '<title id="diagram-title">A &amp; B</title><desc id="diagram-desc">x &lt; y</desc><svg class="d2"'
        in out
    )
    assert out.count("<title") == 1


@needs_d2
def test_a_rendered_svg_has_the_title_and_description_of_its_caption(tmp_path: Path) -> None:
    model = _model(PERSON, SHOP)
    plan = plan_diagrams(model)
    diagram = plan.home["record_shop"]
    (tmp_path / "classes.d2").write_text(CLASSES_D2, encoding="utf-8")
    source = tmp_path / f"{diagram.path}.d2"
    source.parent.mkdir(parents=True)
    source.write_text(render_diagram(model, plan, diagram), encoding="utf-8")
    caption = diagram_caption(model, diagram)
    svg = render_d2(source, tmp_path / "a.svg", caption).decode()
    assert 'role="img"' in svg.split(">", 2)[1] + svg.split(">", 2)[0]
    assert f'<title id="diagram-title">{caption.title}</title>' in svg
    assert svg == render_d2(source, tmp_path / "b.svg", caption).decode()


# --- the D2 version


def test_the_version_is_read_from_d2_version_output() -> None:
    assert parse_d2_version("v0.9.0\n") == "0.9.0"
    assert parse_d2_version("0.9.0") == "0.9.0"


def test_the_pinned_version_passes() -> None:
    check_d2_version(f"v{D2_VERSION}\n")


@pytest.mark.parametrize(
    "output", ["v0.9.1\n", "v0.8.9", "v1.0.0", "v0.10.0", "v0.9.0-rc.1", "0.9.0-beta", "v0.9.0+dev"]
)
def test_another_d2_version_is_refused(output: str) -> None:
    with pytest.raises(D2VersionError, match=re.escape(D2_VERSION)):
        check_d2_version(output)


def test_output_that_is_not_a_version_is_refused() -> None:
    with pytest.raises(D2VersionError, match="can't read"):
        check_d2_version("no such thing")


def test_a_missing_d2_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError(D2_COMMAND)

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(D2VersionError, match="can't run"):
        check_d2_version()


def test_mise_pins_the_version_the_generator_requires() -> None:
    tools = tomllib.loads((REPO_ROOT / "mise.toml").read_text(encoding="utf-8"))["tools"]
    assert tools["d2"] == D2_VERSION


@needs_d2
def test_the_installed_d2_is_the_pinned_version() -> None:
    check_d2_version()


# --- rendering


@needs_d2
def test_a_diagram_renders_with_elk_to_the_same_bytes_twice(tmp_path: Path) -> None:
    model = _model(PERSON, SHOP)
    plan = plan_diagrams(model)
    diagram = plan.home["record_shop"]
    (tmp_path / "classes.d2").write_text(CLASSES_D2, encoding="utf-8")
    source = tmp_path / f"{diagram.path}.d2"
    source.parent.mkdir(parents=True)
    source.write_text(render_diagram(model, plan, diagram), encoding="utf-8")
    first = render_d2(source, tmp_path / "a.svg")
    second = render_d2(source, tmp_path / "b.svg")
    assert D2_LAYOUT == "elk"
    assert first == second
    assert b"<svg" in first


@needs_d2
def test_a_published_diagram_with_every_construct_compiles(tmp_path: Path) -> None:
    contracts = _published()
    model = build_model(contracts)
    plan = plan_diagrams(model)
    (tmp_path / "classes.d2").write_text(CLASSES_D2, encoding="utf-8")
    biggest = max((d for ds in plan.diagrams.values() for d in ds), key=lambda d: len(stubs_of(model, d)))
    source = tmp_path / f"{biggest.path}.d2"
    source.parent.mkdir(parents=True)
    source.write_text(render_diagram(model, plan, biggest), encoding="utf-8")
    assert b"<svg" in render_d2(source, tmp_path / "out.svg")


def test_a_type_too_long_for_one_table_line_is_cut_with_an_ellipsis() -> None:
    names = [f"a_rather_long_definition_name_{n}" for n in range(5)]
    contract = _contract(
        "record/long",
        {
            "type": "object",
            "required": ["level"],
            "properties": {
                "level": {"oneOf": [{"$ref": f"#/$defs/{name}"} for name in names]},
                "short": {"type": "string"},
            },
            "$defs": {name: {"type": "string"} for name in names},
        },
    )
    model = _model(contract)
    plan = plan_diagrams(model)
    source = render_diagram(model, plan, plan.home["record_long"])
    row = next(line for line in source.splitlines() if line.strip().startswith('"level"'))
    cell = row.split(": ", 1)[1].split(" {", 1)[0].strip('"')
    assert len(cell) == MAX_TYPE_CHARS
    assert cell.endswith("…")
    assert '"short": "string"' in source


def test_a_link_starts_with_dot_slash_or_dot_dot_slash_for_d2_to_keep_it() -> None:
    assert svg_link("record/a/01-a.svg", "record/a") == "./01-a.svg"
    assert svg_link("record/a/01-a.svg", "record/b") == "../a/01-a.svg"
    assert svg_link("record/a/01-a.svg", "") == "./record/a/01-a.svg"
    assert svg_link("record/a/01-a.svg", "record/b/c") == "../../a/01-a.svg"


def test_the_render_environment_drops_every_variable_that_changes_a_render() -> None:
    environ = {
        "PATH": "/bin",
        "HOME": "/home/x",
        "D2_THEME": "200",
        "D2_SKETCH": "true",
        "D2_FONT_REGULAR": "/x.ttf",
        "D2_LAYOUT": "dagre",
        "D2_PAD": "0",
        "SCALE": "0.5",
    }
    assert render_env(environ) == {"PATH": "/bin", "HOME": "/home/x"}


def _hrefs(svg: bytes) -> set[str]:
    return {href.decode() for href in re.findall(rb'href="([^"]+)"', svg)}


@needs_d2
def test_rendered_svgs_keep_the_links_of_stubs_in_the_same_directory_and_of_the_overview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("D2_THEME", "200")  # a developer's setting must not reach the render
    wide = _flat_union(30)
    model = _model(wide)
    plan = plan_diagrams(model)
    (tmp_path / "classes.d2").write_text(CLASSES_D2, encoding="utf-8")
    overview = tmp_path / "overview.d2"
    overview.write_text(render_overview(model, plan, ref_counts([wide])), encoding="utf-8")
    sources = {overview: ""}
    for diagram in plan.diagrams["record/wide"]:
        source = tmp_path / f"{diagram.path}.d2"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(render_diagram(model, plan, diagram), encoding="utf-8")
        sources[source] = posixpath.dirname(diagram.path)
    rendered = {}
    for source in sources:
        links = set(re.findall(r'^\s*link: "([^"]+)"$', source.read_text(encoding="utf-8"), re.MULTILINE))
        svg = render_d2(source, source.with_suffix(".svg"))
        assert _hrefs(svg) == links, source.name
        rendered[source] = links
    for source, links in rendered.items():
        for href in links:
            target = posixpath.normpath(posixpath.join(sources[source], href))
            assert (tmp_path / target).with_suffix(".svg").exists(), f"{source.name}: {href}"
    assert sum(len(links) for links in rendered.values()) > len(sources)
