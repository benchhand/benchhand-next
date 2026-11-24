"""Markdown reference pages for docs/contract/generated/, one per contract plus an index."""

from __future__ import annotations

import json
import posixpath
from pathlib import Path
from typing import Any

from .sources import GENERATED_NOTICE, SCHEMA_SUFFIX, Contract

CONSTRAINT_KEYWORDS = (
    "minimum",
    "exclusiveMinimum",
    "maximum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minProperties",
    "maxProperties",
    "format",
    "not",
)


def write_docs(contracts: list[Contract], out_dir: Path) -> None:
    for contract in contracts:
        path = out_dir / f"{contract.stem}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_contract(contract), encoding="utf-8")
    (out_dir / "README.md").write_text(render_index(contracts), encoding="utf-8")


def render_index(contracts: list[Contract]) -> str:
    lines = ["# Contract reference", "", f"{GENERATED_NOTICE} Sources: `contracts/`.", ""]
    for contract in contracts:
        title = contract.schema.get("title", contract.stem)
        lines.append(f"- [{title}]({contract.stem}.md): `{contract.source}`, version {_version(contract)}")
    return "\n".join(lines) + "\n"


def render_contract(contract: Contract) -> str:
    schema = contract.schema
    depth = contract.stem.count("/") + 3  # docs/contract/generated/<dirs>/
    lines = [f"# {schema.get('title', contract.stem)}", ""]
    lines += [f"{GENERATED_NOTICE} Source: [`{contract.source}`]({'../' * depth}{contract.source}).", ""]
    lines += [f"- `$id`: `{contract.schema_id}`", f"- Version: {_version(contract)}", ""]
    if schema.get("description"):
        lines += [schema["description"], ""]
    root = {key: value for key, value in schema.items() if key not in ("$defs", "description", "title")}
    lines += ["## Root", "", *_schema_body(root, contract)]
    definitions = schema.get("$defs", {})
    if definitions:
        lines += ["## Definitions", ""]
    for name, definition in definitions.items():
        lines += [f"### `{name}`", ""]
        if isinstance(definition, dict) and definition.get("description"):
            lines += [definition["description"], ""]
        lines += _schema_body(definition, contract)
    return "\n".join(lines).rstrip("\n") + "\n"


def _version(contract: Contract) -> str:
    return f"`{contract.schema['x-version']}`" if "x-version" in contract.schema else "unversioned"


def _schema_body(schema: Any, contract: Contract) -> list[str]:
    lines = [f"Type: {type_expr(schema, contract)}", ""]
    if not isinstance(schema, dict):
        return lines
    constraints = _constraints(schema)
    if constraints:
        lines += [f"Constraints: {constraints}", ""]
    if schema.get("properties"):
        lines += _properties_table(schema, contract)
    if schema.get("additionalProperties") is False:
        lines += ["No other properties are allowed.", ""]
    elif isinstance(schema.get("additionalProperties"), dict):
        lines += [f"Other properties: {type_expr(schema['additionalProperties'], contract)}", ""]
    for condition in _conditions(schema):
        lines += ["Condition:", "", "```json", json.dumps(condition, indent=2, ensure_ascii=False), "```", ""]
    for example in schema.get("examples", []):
        lines += ["Example:", "", "```json", json.dumps(example, indent=2, ensure_ascii=False), "```", ""]
    return lines


def _properties_table(schema: dict[str, Any], contract: Contract) -> list[str]:
    required = set(schema.get("required", []))
    lines = ["| Property | Type | Required | Description |", "|---|---|---|---|"]
    for name, prop in schema["properties"].items():
        description = prop.get("description", "") if isinstance(prop, dict) else ""
        constraints = _constraints(prop) if isinstance(prop, dict) else ""
        detail = " ".join(part for part in (description, constraints) if part)
        cells = (f"`{name}`", type_expr(prop, contract), "yes" if name in required else "no", detail)
        lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
    return [*lines, ""]


def _conditions(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """The ``if``/``then``/``else`` of ``schema`` and of its ``allOf`` branches, which a table can't show."""
    own = {key: schema[key] for key in ("if", "then", "else") if key in schema}
    branches = [branch for branch in schema.get("allOf", []) if isinstance(branch, dict) and "if" in branch]
    return ([own] if own else []) + branches


def _constraints(schema: dict[str, Any]) -> str:
    found = [f"`{key}: {json.dumps(schema[key])}`" for key in CONSTRAINT_KEYWORDS if key in schema]
    return ", ".join(found)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def type_expr(schema: Any, contract: Contract) -> str:
    """A one-line Markdown description of a schema's type."""
    if schema is True or schema == {}:
        return "any"
    if schema is False:
        return "nothing"
    for keyword, render in _RENDERERS:
        if keyword in schema:
            rendered = render(schema, contract)
            if rendered != "any":
                return rendered
    return "any"


def _ref(schema: dict[str, Any], contract: Contract) -> str:
    target, _, fragment = schema["$ref"].partition("#")
    name = fragment.rsplit("/", 1)[-1] if fragment else ""
    page = ""
    if target:
        page = target.removesuffix(SCHEMA_SUFFIX) + ".md"
    label = name or posixpath.basename(target) or "root"
    return f"[`{label}`]({page}#{name.lower()})" if name else f"[`{label}`]({page})"


def _const(schema: dict[str, Any], _contract: Contract) -> str:
    return f"`{json.dumps(schema['const'], ensure_ascii=False)}`"


def _enum(schema: dict[str, Any], _contract: Contract) -> str:
    return "one of " + ", ".join(f"`{json.dumps(value, ensure_ascii=False)}`" for value in schema["enum"])


def _combinator(keyword: str, joiner: str) -> Any:
    def render(schema: dict[str, Any], contract: Contract) -> str:
        # A branch without a type of its own, such as a condition, leaves the type to the next renderer.
        branches = [type_expr(branch, contract) for branch in schema[keyword]]
        if all(branch == "any" for branch in branches):
            return "any"
        return joiner.join(branches)

    return render


def _type(schema: dict[str, Any], contract: Contract) -> str:
    types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
    rendered = []
    for name in types:
        if name == "array" and "items" in schema:
            rendered.append(f"array of {type_expr(schema['items'], contract)}")
        else:
            rendered.append(name)
    return " or ".join(rendered)


_RENDERERS = (
    ("$ref", _ref),
    ("const", _const),
    ("enum", _enum),
    ("oneOf", _combinator("oneOf", " or ")),
    ("anyOf", _combinator("anyOf", " or ")),
    ("allOf", _combinator("allOf", " and ")),
    ("type", _type),
)
