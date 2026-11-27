# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The command lines of a prototype module, read statically: argparse parsers and subparsers, and click groups
and commands. Nothing is imported or run, so a parser built from data (a loop over a table, a helper that
receives the parser) is only partly seen: an option whose flag is not a literal is kept with ``dynamic`` set.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import NotRequired, TypedDict

from .text import first_line


class OptionRecord(TypedDict):
    flags: list[str]
    """The literal flags (``--hw``), or the name of a positional; the source text when ``dynamic``."""
    kind: str
    """``option`` or ``positional``."""
    help: str
    required: NotRequired[bool]
    default: NotRequired[str]
    """The keyword arguments below are kept as source text, for example ``Path('x')`` or ``('a', 'b')``."""
    choices: NotRequired[str]
    type: NotRequired[str]
    action: NotRequired[str]
    metavar: NotRequired[str]
    nargs: NotRequired[str]
    dest: NotRequired[str]
    dynamic: NotRequired[bool]


class CommandRecord(TypedDict):
    command: str
    """The subcommand words, ``check`` or ``store gc``; empty for the script's own parser or click group."""
    framework: str
    summary: str
    hidden: bool
    line: int
    options: list[OptionRecord]


@dataclass
class _Command:
    path: str
    framework: str
    summary: str
    line: int
    hidden: bool = False
    options: list[OptionRecord] = field(default_factory=list)

    def record(self) -> CommandRecord:
        return {
            "command": self.path,
            "framework": self.framework,
            "summary": self.summary,
            "hidden": self.hidden,
            "line": self.line,
            "options": self.options,
        }


@dataclass(frozen=True)
class _Binding:
    """What a variable holds: a parser (or an argument group of one), or the object ``add_subparsers`` made."""

    kind: str
    command: _Command


_OPTION_KEYS = ("default", "choices", "type", "action", "metavar", "nargs", "dest")
_CLICK_KEYS = ("default", "type", "metavar")
_BOOLEAN_KEYS = ("is_flag", "multiple")


def scan_commands(tree: ast.Module) -> list[CommandRecord]:
    """Every argparse parser and click command in the module, in source order."""
    found = _ArgparseScanner(tree)
    found.body(tree.body, {}, {})
    return [command.record() for command in [*found.commands, *_click_commands(tree, found.doc)]]


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _dotted(node: ast.expr) -> str:
    return ast.unparse(node) if isinstance(node, (ast.Name, ast.Attribute)) else ""


def _text(node: ast.expr, doc: str) -> str:
    """A string argument: the literal, the module docstring's first line for an expression on ``__doc__``, else
    the source text."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if _dotted(node).endswith("SUPPRESS"):
        return ""
    if any(_is_name(child, "__doc__") for child in ast.walk(node)):
        return doc
    return ast.unparse(node)


def _is_suppressed(node: ast.expr | None) -> bool:
    return node is not None and _dotted(node).endswith("SUPPRESS")


def _keywords(call: ast.Call) -> dict[str, ast.expr]:
    return {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}


def _literal_strings(node: ast.expr) -> list[str] | None:
    """The strings of a literal tuple or list, or None when it is anything else."""
    if not isinstance(node, (ast.Tuple, ast.List)):
        return None
    values = [item.value for item in node.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)]
    return values if len(values) == len(node.elts) else None


def _is_true(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


class _ArgparseScanner:
    def __init__(self, tree: ast.Module) -> None:
        self.doc = first_line(ast.get_docstring(tree))
        self.commands: list[_Command] = []
        self._functions = {
            node.name: node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self._tables = {
            node.targets[0].id: node.value
            for node in tree.body
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
        } | {
            node.target.id: node.value
            for node in tree.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None
        }
        self._running: set[str] = set()

    def body(self, statements: list[ast.stmt], env: dict[str, _Binding], names: dict[str, str]) -> None:
        """Follow the statements in order. ``env`` maps variables to the parsers they hold; ``names`` maps the
        loop variables to the string of the pass being followed."""
        for node in statements:
            self._statement(node, env, names)

    def _statement(self, node: ast.stmt, env: dict[str, _Binding], names: dict[str, str]) -> None:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            self._assign(node.targets[0], node.value, env, names)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            self._assign(node.target, node.value, env, names)
        elif isinstance(node, ast.Expr):
            self._owner(node.value, env, names)
        elif isinstance(node, ast.For):
            self._loop(node, env, names)
        elif isinstance(node, ast.If):
            self._branch(node, env, names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.body(node.body, dict(env), names)
        else:
            self._nested(node, env, names)

    def _assign(self, target: ast.expr, value: ast.expr, env: dict[str, _Binding], names: dict[str, str]) -> None:
        if isinstance(target, ast.Tuple) and isinstance(value, ast.Tuple) and len(target.elts) == len(value.elts):
            for part, item in zip(target.elts, value.elts, strict=True):
                self._assign(part, item, env, names)
            return
        binding = self._owner(value, env, names)
        if binding is not None and isinstance(target, ast.Name):
            env[target.id] = binding

    def _nested(self, node: ast.stmt, env: dict[str, _Binding], names: dict[str, str]) -> None:
        """The blocks of a class, with, try or while statement."""
        for block in ("body", "orelse", "finalbody"):
            self.body(getattr(node, block, []), env, names)
        for handler in getattr(node, "handlers", []):
            self.body(handler.body, env, names)

    def _loop(self, node: ast.For, env: dict[str, _Binding], names: dict[str, str]) -> None:
        table = self._tables.get(node.iter.id, node.iter) if isinstance(node.iter, ast.Name) else node.iter
        if isinstance(table, (ast.Tuple, ast.List)):
            for item in table.elts:
                self.body(node.body, env, {**names, **_bound(node.target, item)})
        else:
            self.body(node.body, env, names)
        self.body(node.orelse, env, names)

    def _branch(self, node: ast.If, env: dict[str, _Binding], names: dict[str, str]) -> None:
        verdict = _decide(node.test, names)
        if verdict is not False:
            self.body(node.body, env, names)
        if verdict is not True:
            self.body(node.orelse, env, names)

    def _owner(self, node: ast.expr, env: dict[str, _Binding], names: dict[str, str]) -> _Binding | None:
        """The parser an expression holds. A call is followed for what it adds."""
        if isinstance(node, ast.Name):
            return env.get(node.id)
        if isinstance(node, ast.Subscript):
            return self._choice(node, env)
        if isinstance(node, ast.Call):
            return self._call(node, env, names)
        return None

    def _choice(self, node: ast.Subscript, env: dict[str, _Binding]) -> _Binding | None:
        """``subparsers.choices["name"]``: the parser that ``add_parser("name")`` made."""
        action, key = node.value, node.slice
        if not (isinstance(action, ast.Attribute) and action.attr == "choices" and isinstance(action.value, ast.Name)):
            return None
        owner = env.get(action.value.id)
        if owner is None or not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            return None
        path = f"{owner.command.path} {key.value}".strip()
        return next((_Binding("parser", command) for command in self.commands if command.path == path), None)

    def _call(self, call: ast.Call, env: dict[str, _Binding], names: dict[str, str]) -> _Binding | None:
        if _dotted(call.func).split(".")[-1] == "ArgumentParser":
            return self._parser(call)
        if isinstance(call.func, ast.Name):
            self._helper(call, env)
            return None
        if not isinstance(call.func, ast.Attribute):
            return None
        owner = self._owner(call.func.value, env, names)
        if owner is None:
            return None
        method = call.func.attr
        if method == "add_subparsers":
            return _Binding("subparsers", owner.command)
        if method == "add_parser" and owner.kind == "subparsers":
            return self._subparser(call, owner.command, names)
        if method == "add_argument" and owner.kind == "parser":
            owner.command.options.append(_argparse_option(call, self.doc, names))
        return owner if method in ("add_mutually_exclusive_group", "add_argument_group") else None

    def _helper(self, call: ast.Call, env: dict[str, _Binding]) -> None:
        """A call of a function in this module with a parser as an argument: follow the function's body with its
        parameter bound to that parser."""
        if not isinstance(call.func, ast.Name):
            return
        function = self._functions.get(call.func.id)
        if function is None or function.name in self._running:
            return
        parameters = [argument.arg for argument in [*function.args.posonlyargs, *function.args.args]]
        inner = {
            parameter: env[argument.id]
            for parameter, argument in zip(parameters, call.args, strict=False)
            if isinstance(argument, ast.Name) and argument.id in env
        }
        if inner:
            self._running.add(function.name)
            self.body(function.body, inner, {})
            self._running.discard(function.name)

    def _parser(self, call: ast.Call) -> _Binding:
        description = _keywords(call).get("description")
        summary = _text(description, self.doc) if description is not None else ""
        command = _Command("", "argparse", summary, call.lineno)
        self.commands.append(command)
        return _Binding("parser", command)

    def _subparser(self, call: ast.Call, parent: _Command, names: dict[str, str]) -> _Binding:
        keywords = _keywords(call)
        word = _subcommand_word(call.args[0], names) if call.args else ast.unparse(keywords.get("name", call.func))
        summary_node = keywords.get("help") or keywords.get("description")
        command = _Command(
            f"{parent.path} {word}".strip(),
            "argparse",
            _text(summary_node, self.doc) if summary_node is not None else "",
            call.lineno,
            hidden=_is_suppressed(keywords.get("help")),
        )
        self.commands.append(command)
        return _Binding("parser", command)


def _bound(target: ast.expr, item: ast.expr) -> dict[str, str]:
    """The loop variables that one item of a literal table gives a string."""
    if isinstance(target, ast.Name):
        return {target.id: item.value} if isinstance(item, ast.Constant) and isinstance(item.value, str) else {}
    if isinstance(target, ast.Tuple) and isinstance(item, (ast.Tuple, ast.List)) and len(item.elts) == len(target.elts):
        bound: dict[str, str] = {}
        for part, value in zip(target.elts, item.elts, strict=True):
            bound |= _bound(part, value)
        return bound
    return {}


def _subcommand_word(node: ast.expr, names: dict[str, str]) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in names:
        return names[node.id]
    return f"<{ast.unparse(node)}>"


def _decide(test: ast.expr, names: dict[str, str]) -> bool | None:
    """The value of ``name == "x"``, ``name != "x"`` or ``name in ("x", "y")`` for a loop variable, else None."""
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.left, ast.Name)):
        return None
    if test.left.id not in names:
        return None
    current, operator, other = names[test.left.id], test.ops[0], test.comparators[0]
    if isinstance(operator, (ast.Eq, ast.NotEq)) and isinstance(other, ast.Constant):
        return (current == other.value) == isinstance(operator, ast.Eq)
    options = _literal_strings(other)
    if isinstance(operator, (ast.In, ast.NotIn)) and options is not None:
        return (current in options) == isinstance(operator, ast.In)
    return None


def _flag(node: ast.expr, names: dict[str, str]) -> str | None:
    """A flag written out, or held by a loop variable of a literal table; None when it is computed."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return names.get(node.id) if isinstance(node, ast.Name) else None


def _argparse_option(call: ast.Call, doc: str, names: dict[str, str]) -> OptionRecord:
    keywords = _keywords(call)
    literal = [_flag(arg, names) for arg in call.args]
    dynamic = None in literal or not literal
    flags = [ast.unparse(arg) for arg in call.args] if dynamic else [flag for flag in literal if flag]
    positional = not dynamic and not flags[0].startswith("-")
    help_node = keywords.get("help")
    record: OptionRecord = {
        "flags": flags,
        "kind": "positional" if positional else "option",
        "help": _text(help_node, doc) if help_node is not None else "",
    }
    if _is_true(keywords.get("required")):
        record["required"] = True
    for key in _OPTION_KEYS:
        if key in keywords:
            record[key] = ast.unparse(keywords[key])  # type: ignore[literal-required]
    if dynamic:
        record["dynamic"] = True
    return record


def _click_commands(tree: ast.Module, doc: str) -> list[_Command]:
    """Commands made by ``@click.group``, ``@click.command`` and ``@<group>.command`` on a top-level function.
    Options come from the ``@click.option`` and ``@click.argument`` decorators, or from a module-level name
    bound to one of those calls."""
    aliases = {
        target.id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
        for target in node.targets
        if isinstance(target, ast.Name) and _dotted(node.value.func).startswith("click.")
    }
    groups: dict[str, str] = {}
    found: list[_Command] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = [_decorator_call(item, aliases) for item in node.decorator_list]
        command = next(
            (made for call in decorators if (made := _click_command(node, call, groups, doc)) is not None), None
        )
        if command is not None:
            command.options = [_click_option(call, doc) for call in decorators if _is_click_option(call)]
            found.append(command)
    return found


def _decorator_call(node: ast.expr, aliases: dict[str, ast.Call]) -> ast.Call:
    """The call a decorator makes; a bare name or attribute becomes a call without arguments."""
    if isinstance(node, ast.Name) and node.id in aliases:
        return aliases[node.id]
    if isinstance(node, ast.Call):
        return node
    return ast.Call(func=node, args=[], keywords=[])


def _is_click_option(call: ast.Call) -> bool:
    return _dotted(call.func) in ("click.option", "click.argument")


def _click_command(
    function: ast.FunctionDef | ast.AsyncFunctionDef, call: ast.Call, groups: dict[str, str], doc: str
) -> _Command | None:
    """The command a decorator declares, and a group's path is remembered under its function name."""
    callee = _dotted(call.func)
    owner, _, kind = callee.rpartition(".")
    if kind not in ("group", "command") or not (owner == "click" or owner in groups):
        return None
    keywords = _keywords(call)
    name = keywords.get("name")
    word = name.value if isinstance(name, ast.Constant) else function.name.replace("_", "-")
    path = "" if owner == "click" else f"{groups[owner]} {word}".strip()
    if kind == "group":
        groups[function.name] = path
    help_node = keywords.get("help")
    summary = _text(help_node, doc) if help_node is not None else first_line(ast.get_docstring(function))
    return _Command(path, "click", summary, function.lineno, hidden=_is_true(keywords.get("hidden")))


def _click_option(call: ast.Call, doc: str) -> OptionRecord:
    keywords = _keywords(call)
    strings = [arg.value for arg in call.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)]
    is_argument = _dotted(call.func) == "click.argument"
    flags = strings[:1] if is_argument else [text for text in strings if text.startswith("-")]
    help_node = keywords.get("help")
    record: OptionRecord = {
        "flags": flags,
        "kind": "positional" if is_argument else "option",
        "help": _text(help_node, doc) if help_node is not None else "",
    }
    if _is_true(keywords.get("required")):
        record["required"] = True
    for key in _CLICK_KEYS:
        if key in keywords:
            record[key] = ast.unparse(keywords[key])  # type: ignore[literal-required]
    type_node = keywords.get("type")
    if isinstance(type_node, ast.Call) and _dotted(type_node.func) == "click.Choice" and type_node.args:
        record["choices"] = ast.unparse(type_node.args[0])
    dests = [text for text in strings if not text.startswith("-")] if not is_argument else []
    if dests:
        record["dest"] = repr(dests[0])
    for key in _BOOLEAN_KEYS:
        if _is_true(keywords.get(key)):
            record["nargs" if key == "multiple" else "action"] = key
    return record
