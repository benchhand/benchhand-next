# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Generate CEL type artefacts from the published contract schemas.

One run reads `scopes.yaml`, walks every published JSON Schema node an activation variable can reach, and
writes:

- one `.proto` file per contract that a scope reaches, compiled by `buf build` into a FileDescriptorSet;
- one cel-go environment YAML per scope, naming each variable's message type.

Only structural schemas are typed, in the sense Kubernetes uses for CRDs: every node a rule can reach must
have one shape. A oneOf or anyOf whose branches carry different shapes (a union), an allOf that merges
shapes, and an untyped node (`true` or `{}`, which would be `dyn`) are refused. A scope may list such a
node in `omit`; the field is then left out of the message, so a rule that reads it fails the type check.
Validation-only keywords (pattern, bounds, if/then/else, not, and a oneOf or anyOf of `required` clauses)
don't change the shape and are ignored.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SCHEMAS = REPO / "packages/benchhand-contracts/src/benchhand_contracts/schemas"
PROTO_ROOT = "benchhand.contracts"

# Keywords that constrain a value without changing its shape.
VALIDATION_ONLY = {
    "$schema",
    "$id",
    "title",
    "description",
    "examples",
    "default",
    "x-version",
    "pattern",
    "format",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minProperties",
    "maxProperties",
    "required",
    "dependentRequired",
    "propertyNames",
    "if",
    "then",
    "else",
    "not",
    "$defs",
}
SHAPE_KEYWORDS = {"type", "properties", "items", "additionalProperties", "$ref", "enum", "const"}
COMBINATORS = ("oneOf", "anyOf", "allOf")
# CEL reserved words can't be selected with `x.name`.
CEL_RESERVED = set(
    "as break const continue else false for function if import in let loop package namespace null "
    "return true var void while".split()
)
SCALARS = {"string": "string", "integer": "int64", "number": "double", "boolean": "bool"}
WRAPPERS = {
    "string": "google.protobuf.StringValue",
    "int64": "google.protobuf.Int64Value",
    "double": "google.protobuf.DoubleValue",
    "bool": "google.protobuf.BoolValue",
}


class NotStructural(Exception):
    """A schema node a rule could reach has no single shape."""


@dataclass(frozen=True)
class Location:
    """A node in a published schema: its file (relative to the schemas root) and JSON pointer."""

    file: str
    pointer: str

    def __str__(self) -> str:
        return f"{self.file}#{self.pointer}"


@dataclass(frozen=True)
class ProtoType:
    """A field's type. `kind` is scalar, message, map or list; `name` is the scalar or message name."""

    kind: str
    name: str
    element: ProtoType | None = None
    nullable: bool = False


@dataclass
class ProtoField:
    name: str
    type: ProtoType
    required: bool
    comment: str = ""


@dataclass
class ProtoMessage:
    package: str
    name: str
    source: Location
    fields: list[ProtoField] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.package}.{self.name}"


def pascal(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[_\-]", name) if part)


def package_for(schema_file: str) -> str:
    stem = schema_file.removesuffix(".schema.json").replace("/", ".").replace("-", "_")
    return f"{PROTO_ROOT}.{stem}"


class Schemas:
    """Loads published schema files and resolves file-relative `$ref`s."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.cache: dict[str, dict] = {}

    def document(self, file: str) -> dict:
        if file not in self.cache:
            self.cache[file] = json.loads((self.root / file).read_text())
        return self.cache[file]

    def node(self, loc: Location) -> object:
        current: object = self.document(loc.file)
        for token in [t for t in loc.pointer.split("/") if t]:
            current = current[token.replace("~1", "/").replace("~0", "~")]  # type: ignore[index]
        return current

    def resolve(self, ref: str, base: Location) -> Location:
        target_file, _, pointer = ref.partition("#")
        if target_file:
            target_file = str((Path(base.file).parent / target_file).as_posix())
        return Location(target_file or base.file, pointer)


def nullable_branch(branches: list) -> object | None:
    """The non-null branch of a two-branch union with `{"type": "null"}`, or None."""
    if len(branches) != 2:
        return None
    nulls = [b for b in branches if b == {"type": "null"}]
    others = [b for b in branches if b != {"type": "null"}]
    return others[0] if len(nulls) == 1 else None


def has_shape(node: object) -> bool:
    """Whether a schema node declares or changes a shape (as opposed to only constraining values)."""
    if not isinstance(node, dict):
        return node is not True
    if SHAPE_KEYWORDS & node.keys():
        return True
    return any(has_shape(b) for key in COMBINATORS for b in node.get(key, []))


class Generator:
    def __init__(self, schemas: Schemas, omit: set[str]) -> None:
        self.schemas = schemas
        self.omit = omit
        self.messages: dict[str, ProtoMessage] = {}
        self.refusals: list[str] = []
        self.omitted: list[str] = []

    def message_for(self, node: dict, loc: Location, hint: str) -> ProtoType:
        package = package_for(loc.file)
        name = (
            pascal(loc.pointer.rsplit("/", 1)[-1])
            if loc.pointer
            else pascal(Path(loc.file).name.split(".")[0])
        )
        if loc.pointer and not loc.pointer.startswith("/$defs/"):
            name = hint
        full = f"{package}.{name}"
        if full not in self.messages:
            message = ProtoMessage(package, name, loc)
            self.messages[full] = message
            self.fill(message, node, loc)
        return ProtoType("message", full)

    def fill(self, message: ProtoMessage, node: dict, loc: Location) -> None:
        required = set(node.get("required", []))
        for prop, sub in node.get("properties", {}).items():
            where = Location(loc.file, f"{loc.pointer}/properties/{prop}")
            if str(where) in self.omit:
                self.omitted.append(str(where))
                continue
            if prop in CEL_RESERVED:
                self.refusals.append(f"{where}: the field name is a CEL reserved word")
                continue
            try:
                ptype = self.type_of(sub, where, f"{message.name}{pascal(prop)}")
            except NotStructural as exc:
                self.refusals.append(f"{where}: {exc}")
                continue
            message.fields.append(ProtoField(prop, ptype, prop in required, enum_comment(sub)))

    def type_of(self, node: object, loc: Location, hint: str) -> ProtoType:
        if not isinstance(node, dict) or not has_shape(node):
            raise NotStructural("an untyped node (true or {}) would be dyn")
        if "$ref" in node:
            return self.ref_type(node, loc, hint)
        for key in COMBINATORS:
            if key in node:
                return self.combinator_type(node, key, loc, hint)
        return self.typed(node, loc, hint)

    def ref_type(self, node: dict, loc: Location, hint: str) -> ProtoType:
        if SHAPE_KEYWORDS & (node.keys() - {"$ref"}):
            raise NotStructural("a $ref with shape-bearing sibling keywords")
        target = self.schemas.resolve(node["$ref"], loc)
        return self.type_of(self.schemas.node(target), target, hint)

    def combinator_type(self, node: dict, key: str, loc: Location, hint: str) -> ProtoType:
        branches = node[key]
        inner = nullable_branch(branches) if key != "allOf" else None
        if inner is not None:
            base = self.type_of(inner, Location(loc.file, f"{loc.pointer}/{key}/0"), hint)
            if base.kind != "scalar":
                # Only scalar-or-null is a nullable scalar. A message, list or map or null has two
                # readings of absence (null and empty), so it is a union like any other.
                raise NotStructural(f"{key} of a {base.kind} and null isn't a nullable scalar")
            return ProtoType(base.kind, base.name, base.element, nullable=True)
        if any(has_shape(b) for b in branches):
            kind = "a union" if key != "allOf" else "a merge of shapes"
            raise NotStructural(f"{key} with shape-bearing branches is {kind}")
        rest = {k: v for k, v in node.items() if k != key}
        return self.type_of(rest, loc, hint)

    def typed(self, node: dict, loc: Location, hint: str) -> ProtoType:
        types = node.get("type")
        types = [types] if isinstance(types, str) else list(types or [])
        nullable = "null" in types
        types = [t for t in types if t != "null"]
        if not types:
            return self.untyped_values(node)
        if len(types) > 1:
            raise NotStructural(f"a node of several types {types}")
        base = self.single(types[0], node, loc, hint)
        if nullable and base.kind != "scalar":
            raise NotStructural(f"a {base.kind} or null isn't a nullable scalar")
        return ProtoType(base.kind, base.name, base.element, nullable=nullable)

    def untyped_values(self, node: dict) -> ProtoType:
        values = node.get("enum", [node["const"]] if "const" in node else [])
        kinds = {type(v) for v in values}
        if kinds == {str}:
            return ProtoType("scalar", "string")
        raise NotStructural(f"an enum or const of {sorted(k.__name__ for k in kinds)}")

    def single(self, kind: str, node: dict, loc: Location, hint: str) -> ProtoType:
        if kind in SCALARS:
            return ProtoType("scalar", SCALARS[kind])
        if kind == "array":
            if "items" not in node:
                raise NotStructural("an array without items would be list(dyn)")
            element = self.type_of(node["items"], Location(loc.file, f"{loc.pointer}/items"), hint)
            if element.kind in ("list", "map"):
                raise NotStructural("a list of lists or maps has no proto field type")
            return ProtoType("list", "", element)
        if kind == "object":
            return self.object_type(node, loc, hint)
        raise NotStructural(f"the JSON type {kind}")

    def object_type(self, node: dict, loc: Location, hint: str) -> ProtoType:
        extra = node.get("additionalProperties", True)
        if "properties" in node:
            if extra is not False:
                raise NotStructural("an object with properties that isn't sealed")
            return self.message_for(node, loc, hint)
        if isinstance(extra, dict):
            where = Location(loc.file, f"{loc.pointer}/additionalProperties")
            value = self.type_of(extra, where, hint)
            if value.kind in ("list", "map"):
                raise NotStructural("a map of lists or maps has no proto field type")
            return ProtoType("map", "", value)
        raise NotStructural("an object without properties would be map(string, dyn)")


def enum_comment(node: object) -> str:
    if isinstance(node, dict) and isinstance(node.get("enum"), list):
        return "one of: " + ", ".join(map(str, node["enum"]))
    return ""


def proto_field_type(ptype: ProtoType) -> str:
    if ptype.kind == "list":
        assert ptype.element is not None
        return f"repeated {proto_field_type(ProtoType(ptype.element.kind, ptype.element.name))}"
    if ptype.kind == "map":
        assert ptype.element is not None
        return f"map<string, {proto_field_type(ProtoType(ptype.element.kind, ptype.element.name))}>"
    if ptype.kind == "scalar" and ptype.nullable:
        return WRAPPERS[ptype.name]
    return ptype.name if ptype.kind == "scalar" else f".{ptype.name}"


def field_line(number: int, pf: ProtoField) -> str:
    ftype = proto_field_type(pf.type)
    presence = ""
    if pf.type.kind == "scalar" and not pf.type.nullable and not pf.required:
        presence = "optional "
    comment = f"  // {pf.comment}" if pf.comment else ""
    return f"  {presence}{ftype} {pf.name} = {number}; {comment}".rstrip()


def render_proto(file: str, messages: list[ProtoMessage], imports: set[str]) -> str:
    lines = [
        "// Generated by research/cel-neutral/gen/celgen.py from the published JSON Schema. Don't edit.",
        f"// Source: {file}",
        'syntax = "proto3";',
        f"package {package_for(file)};",
        "",
    ]
    lines += [f'import "{imp}";' for imp in sorted(imports)]
    for message in messages:
        lines += ["", f"// {message.source}", f"message {message.name} {{"]
        lines += [field_line(i, pf) for i, pf in enumerate(message.fields, start=1)]
        lines.append("}")
    return "\n".join(lines) + "\n"


def proto_path(file: str) -> str:
    return "benchhand/contracts/" + file.removesuffix(".schema.json").replace("-", "_") + ".proto"


def imports_for(messages: list[ProtoMessage], by_name: dict[str, ProtoMessage], own_file: str) -> set[str]:
    imports: set[str] = set()
    for message in messages:
        for pf in message.fields:
            leaf = pf.type.element or pf.type
            if pf.type.kind == "scalar" and pf.type.nullable:
                imports.add("google/protobuf/wrappers.proto")
            if leaf.kind == "message" and by_name[leaf.name].source.file != own_file:
                imports.add(proto_path(by_name[leaf.name].source.file))
    return imports


def write_protos(gen: Generator, out: Path) -> list[str]:
    by_file: dict[str, list[ProtoMessage]] = {}
    for message in gen.messages.values():
        by_file.setdefault(message.source.file, []).append(message)
    written = []
    for file, messages in sorted(by_file.items()):
        target = out / "proto" / proto_path(file)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_proto(file, messages, imports_for(messages, gen.messages, file)))
        written.append(str(target.relative_to(out)))
    return written


def env_config(scope: str, spec: dict, types: dict[str, str]) -> dict:
    variables = [
        {"name": name, "type_name": types[name], "description": variable_source(var)}
        for name, var in spec["variables"].items()
    ]
    config: dict = {"name": scope}
    if spec.get("extensions"):
        config["extensions"] = [{"name": e["name"], "version": e["version"]} for e in spec["extensions"]]
    config["variables"] = variables
    return config


# The CEL primitive types a scope may declare directly, for a variable that no schema node types.
CEL_PRIMITIVES = {"string", "int", "uint", "double", "bool", "bytes"}


def variable_source(var: dict) -> str:
    if "type" in var:
        return f"primitive {var['type']}"
    return f"{var['schema']}#{var.get('pointer', '')}"


def generate_scope(schemas: Schemas, scope: str, spec: dict) -> tuple[Generator, dict[str, str]]:
    omit = set(spec.get("omit", []))
    gen = Generator(schemas, omit)
    types: dict[str, str] = {}
    for name, var in spec["variables"].items():
        if "type" in var:
            if var["type"] not in CEL_PRIMITIVES:
                gen.refusals.append(f"{scope}.{name}: {var['type']} isn't a CEL primitive type")
            types[name] = var["type"]
            continue
        loc = Location(var["schema"], var.get("pointer", ""))
        try:
            types[name] = gen.type_of(schemas.node(loc), loc, pascal(name)).name
        except NotStructural as exc:
            gen.refusals.append(f"{loc}: {exc}")
    stale = omit - set(gen.omitted)
    gen.refusals += [f"{entry}: listed in omit but not reached" for entry in sorted(stale)]
    return gen, types


def run_scope(schemas: Schemas, scope: str, spec: dict, out: Path, report: list[str]) -> Generator | None:
    """Generate one scope. Returns its generator when it is structural, None when refused."""
    gen, types = generate_scope(schemas, scope, spec)
    expected = spec.get("expect", "structural")
    if gen.refusals:
        report.append(f"scope {scope}: refused, not structural (expected {expected})")
        report.extend(f"  {r}" for r in gen.refusals)
        return None
    report.append(f"scope {scope}: structural, {len(gen.messages)} messages (expected {expected})")
    report.extend(f"  omitted {entry}" for entry in gen.omitted)
    env_dir = out / "env"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / f"{scope}.env.yaml").write_text(
        yaml.safe_dump(env_config(scope, spec, types), sort_keys=False)
    )
    return gen


def merge_messages(merged: dict[str, ProtoMessage], new: dict[str, ProtoMessage]) -> list[str]:
    """Add one scope's messages to the shared set. A schema node maps to one protobuf message whatever the
    scope, so two scopes that project the same node with different fields (different omissions) would
    share one message with the wrong field set. That is refused, with the message and both field lists;
    the merged set keeps the first projection."""
    conflicts = []
    for full, message in new.items():
        old = merged.get(full)
        if old is None:
            merged[full] = message
            continue
        if [(f.name, f.type) for f in old.fields] != [(f.name, f.type) for f in message.fields]:
            have = sorted(f.name for f in old.fields)
            want = sorted(f.name for f in message.fields)
            conflicts.append(
                f"conflicting projection of {full} ({message.source}): fields {want}, another scope has {have}"
            )
    return conflicts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate CEL type artefacts from the published contract schemas."
    )
    parser.add_argument("scopes", type=Path, help="the activation scopes file")
    parser.add_argument("--out", type=Path, required=True, help="where to write proto/, env/ and scopes.txt")
    parser.add_argument("--schemas", type=Path, default=SCHEMAS)
    args = parser.parse_args(argv)
    scopes = yaml.safe_load(args.scopes.read_text())["scopes"]
    schemas = Schemas(args.schemas)
    merged = Generator(schemas, set())
    report: list[str] = []
    unexpected = []
    for scope, spec in scopes.items():
        gen = run_scope(schemas, scope, spec, args.out, report)
        if (gen is None) != (spec.get("expect") == "refused"):
            unexpected.append(scope)
        if gen is not None:
            conflicts = merge_messages(merged.messages, gen.messages)
            report.extend(f"scope {scope}: {c}" for c in conflicts)
            if conflicts:
                unexpected.append(scope)
    report += [f"wrote {path}" for path in write_protos(merged, args.out)]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "scopes.txt").write_text("\n".join(report) + "\n")
    print("\n".join(report))
    if unexpected:
        print(f"scopes not as expected: {unexpected}", file=sys.stderr)
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
