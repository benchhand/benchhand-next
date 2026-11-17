#!/usr/bin/env python3
"""cad-record cli.py: Click options from a JSON Schema config, and the loader's source reporting.

Run: uv run --no-project --with click==8.5.1 python -B -m unittest discover -s skills/cad-record/tests -p test_cli.py -v
The config loader is a local stand-in (fixtures/config_loader_standin.py) until config_loader.py lands.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import click
from click.testing import CliRunner

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
from modload import load_fresh, load_module  # noqa: E402

emit = load_module("cad_record_emit", SKILLS / "cad-record" / "scripts" / "emit.py")
CLI_PATH = SKILLS / "cad-record" / "scripts" / "cli.py"
cli_mod = load_module("cad_record_cli", CLI_PATH)
loader = load_module("config_loader_standin", HERE / "fixtures" / "config_loader_standin.py")

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "count": {"type": "integer", "minimum": 1, "maximum": 5, "x-cli": "--count"},
        "rank": {"type": "integer", "exclusiveMinimum": 0, "exclusiveMaximum": 4, "x-cli": "--rank"},
        "band": {"type": "number", "minimum": 0, "exclusiveMaximum": 10, "default": 2.5,
                 "x-cli": "--mesh-band", "x-env": "CAD_BAND", "description": "Band width."},
        "pitch": {"type": "number", "exclusiveMinimum": 0, "maximum": 1, "x-cli": "--pitch"},
        "kind": {"type": "string", "enum": ["fine", "coarse"], "x-cli": "--kind"},
        "verbose": {"type": "boolean", "x-cli": "--verbose"},
        "refit": {"type": "boolean", "x-cli": "--refit/--no-refit", "x-env": "CAD_REFIT"},
        "cache": {"type": "boolean", "default": True, "x-cli": "--cache/--no-cache"},
        "label": {"type": "string", "x-cli": "--label"},
        "free": {"type": "number", "x-cli": "--free"},
        "mesh": {"type": "object", "properties": {
            "tol": {"type": "number", "default": 0.1, "x-cli": "--mesh-tol", "x-env": "CAD_MESH_TOL"}}},
        "plain": {"type": "number", "default": 1.0},
    },
}


class Harness:
    """A command over SCHEMA that records its parameters and the CLI layer it built."""

    def __init__(self, ldr: Any = loader, schema: Mapping[str, Any] = SCHEMA) -> None:
        self.schema = schema
        self.cli = cli_mod.SchemaCLI(schema, ldr, tool="probe")
        self.params: dict[str, Any] = {}
        self.layer: Any = None
        self.resolved: Any = None

    def run(self, args: list[str], *, env: Mapping[str, str] | None = None, config: Any = None):
        @click.pass_context
        def callback(ctx: click.Context, **params: Any) -> None:
            self.params = params
            self.layer = self.cli.layer(ctx)
            self.resolved = self.cli.resolve(ctx, config if config is not None else loader.load(self.schema, env=env),
                                             json_flag=True)

        command = click.Command("probe", params=self.cli.params(), callback=callback)
        default_map = self.cli.default_map(config) if config is not None else None
        return CliRunner().invoke(command, args, env=dict(env or {}), default_map=default_map)


class OptionTests(unittest.TestCase):
    def test_each_type_reaches_the_command_as_its_python_type(self) -> None:
        cases = [
            (["--count", "3"], "count", 3),
            (["--mesh-band", "1.5"], "mesh_band", 1.5),
            (["--free", "-7.25"], "free", -7.25),
            (["--kind", "coarse"], "kind", "coarse"),
            (["--verbose"], "verbose", True),
            (["--refit"], "refit", True),
            (["--no-refit"], "refit", False),
            (["--label", "x y"], "label", "x y"),
        ]
        for args, name, expected in cases:
            with self.subTest(args=args):
                harness = Harness()
                result = harness.run(args)
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(harness.params[name], expected)
                self.assertIs(type(harness.params[name]), type(expected))

    def test_bounds_closed_and_open(self) -> None:
        cases = [
            (["--count", "1"], True), (["--count", "0"], False),
            (["--count", "5"], True), (["--count", "6"], False),
            (["--rank", "1"], True), (["--rank", "0"], False),
            (["--rank", "3"], True), (["--rank", "4"], False),
            (["--mesh-band", "0"], True), (["--mesh-band", "-0.1"], False),
            (["--mesh-band", "9.9"], True), (["--mesh-band", "10"], False),
            (["--pitch", "0.1"], True), (["--pitch", "0"], False),
            (["--pitch", "1"], True), (["--pitch", "1.1"], False),
        ]
        for args, accepted in cases:
            with self.subTest(args=args):
                result = Harness().run(args)
                self.assertEqual(result.exit_code, 0 if accepted else 2, result.output)

    def test_an_out_of_range_flag_is_a_plain_text_usage_error(self) -> None:
        result = Harness().run(["--count", "9"])
        self.assertEqual(result.exit_code, 2)
        self.assertIn("Invalid value for '--count'", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_enum_accepts_members_and_rejects_others(self) -> None:
        self.assertEqual(Harness().run(["--kind", "fine"]).exit_code, 0)
        result = Harness().run(["--kind", "medium"])
        self.assertEqual(result.exit_code, 2)
        self.assertIn("Invalid value for '--kind'", result.stderr)

    def test_the_schema_default_applies_when_nothing_is_given(self) -> None:
        harness = Harness()
        self.assertEqual(harness.run([]).exit_code, 0)
        self.assertEqual(harness.params["mesh_band"], 2.5)
        self.assertEqual(harness.params["mesh_tol"], 0.1)
        self.assertIsNone(harness.params["count"])

    def test_the_flag_comes_from_x_cli_and_a_field_without_it_has_no_option(self) -> None:
        names = {opt for param in Harness().cli.params() for opt in param.opts}
        self.assertIn("--mesh-band", names)
        self.assertNotIn("--band", names)
        self.assertFalse(any("plain" in name for name in names))

    def test_help_shows_the_schema_description(self) -> None:
        result = Harness().run(["--help"])
        self.assertIn("Band width.", result.stdout)

    def test_the_env_var_comes_from_x_env_with_the_same_range_check(self) -> None:
        harness = Harness()
        self.assertEqual(harness.run([], env={"CAD_BAND": "3"}).exit_code, 0)
        self.assertEqual(harness.params["mesh_band"], 3.0)
        bad = Harness().run([], env={"CAD_BAND": "10"})
        self.assertEqual(bad.exit_code, 2)
        self.assertIn("Invalid value for '--mesh-band'", bad.stderr)


class BooleanTests(unittest.TestCase):
    def test_a_paired_flag_reports_the_half_that_was_given(self) -> None:
        cases = [("--refit", True, "cli:--refit"), ("--no-refit", False, "cli:--no-refit")]
        for arg, value, source in cases:
            with self.subTest(arg=arg):
                harness = Harness()
                self.assertEqual(harness.run([arg]).exit_code, 0)
                self.assertEqual(harness.layer.values, {"refit": value})
                self.assertEqual(harness.layer.sources, {"/refit": source})
                self.assertEqual(harness.resolved.sources["/refit"], source)

    def test_a_paired_flag_left_out_keeps_its_default_and_stays_out_of_the_cli_layer(self) -> None:
        harness = Harness()
        self.assertEqual(harness.run([]).exit_code, 0)
        self.assertEqual(harness.layer.sources, {})
        self.assertIs(harness.resolved.values["cache"], True)
        self.assertEqual(harness.resolved.sources["/cache"], "default")

    def test_a_store_true_flag_is_true_when_given_and_false_when_not(self) -> None:
        given, absent = Harness(), Harness()
        given.run(["--verbose"])
        absent.run([])
        self.assertIs(given.params["verbose"], True)
        self.assertEqual(given.layer.sources, {"/verbose": "cli:--verbose"})
        self.assertIs(absent.params["verbose"], False)
        self.assertEqual(absent.layer.sources, {})

    def test_a_store_true_flag_takes_no_value(self) -> None:
        self.assertEqual(Harness().run(["--verbose", "true"]).exit_code, 2)

    def test_the_env_var_sets_a_boolean_and_is_not_a_cli_source(self) -> None:
        for text, value in (("true", True), ("false", False)):
            with self.subTest(text=text):
                harness = Harness()
                self.assertEqual(harness.run([], env={"CAD_REFIT": text}).exit_code, 0)
                self.assertIs(harness.params["refit"], value)
                self.assertEqual(harness.layer.sources, {})
                self.assertEqual(harness.resolved.sources["/refit"], "env:CAD_REFIT")

    def test_an_env_var_that_is_not_a_boolean_is_a_usage_error(self) -> None:
        result = Harness().run([], env={"CAD_REFIT": "maybe"})
        self.assertEqual(result.exit_code, 2)
        self.assertIn("Invalid value", result.stderr)


class LazyTests(unittest.TestCase):
    def test_click_is_needed_only_when_a_flag_help_or_an_env_var_is_present(self) -> None:
        cli = Harness().cli
        cases = [
            (["run"], {}, False),
            (["run", "--plain-name", "x"], {"PATH": "/bin"}, False),
            (["run", "--count", "3"], {}, True),
            (["run", "--count=3"], {}, True),
            (["run", "--no-refit"], {}, True),
            (["run", "--mesh-band", "1"], {}, True),
            (["run", "--help"], {}, True),
            (["run"], {"CAD_BAND": "3"}, True),
        ]
        for argv, environ, expected in cases:
            with self.subTest(argv=argv, environ=environ):
                self.assertIs(cli.needs_click(argv, environ), expected)

    def test_the_process_environment_is_accepted_when_some_fields_have_no_env_var(self) -> None:
        with mock.patch.dict("os.environ", {"CAD_BAND": "3"}):
            self.assertTrue(Harness().cli.needs_click(["run"], os.environ))
        with mock.patch.dict("os.environ", clear=True):
            self.assertFalse(Harness().cli.needs_click(["run"], os.environ))


def one(**field: Any) -> dict[str, Any]:
    return {"properties": {"f": {"x-cli": "--f", **field}}}


def two(first: str, second: str, **extra: Any) -> dict[str, Any]:
    return {"properties": {"a": {"type": "integer", "x-cli": first, **extra}, "b": {"type": "integer", "x-cli": second}}}


class ConstructionTests(unittest.TestCase):
    def refused(self, schema: Mapping[str, Any], pattern: str) -> None:
        with self.assertRaisesRegex(ValueError, pattern):
            cli_mod.SchemaCLI(schema, loader, tool="probe")

    def test_an_unsupported_type_is_refused(self) -> None:
        self.refused(one(type="array"), "--f.*unsupported type")

    def test_a_non_string_enum_is_refused(self) -> None:
        self.refused(one(type="integer", enum=[1, 2]), "--f.*only string enums")

    def test_two_fields_with_the_same_flag_are_refused(self) -> None:
        self.refused(two("--x", "--x"), "duplicate flag")

    def test_a_negative_half_that_another_field_spells_is_refused(self) -> None:
        schema = {"properties": {"a": {"type": "boolean", "x-cli": "--x/--no-x"},
                                 "b": {"type": "boolean", "x-cli": "--no-x"}}}
        self.refused(schema, "duplicate flag")

    def test_two_flags_that_make_one_parameter_name_are_refused(self) -> None:
        self.refused(two("--a-b", "--a_b"), "duplicate parameter name")

    def test_a_short_flag_is_refused_in_either_half_of_a_pair(self) -> None:
        for declaration in ("-n", "--x/-n"):
            with self.subTest(declaration=declaration):
                self.refused({"properties": {"a": {"type": "boolean", "x-cli": declaration}}}, "only long --flags")

    def test_draft_4_boolean_exclusive_bounds_are_refused(self) -> None:
        for key in ("exclusiveMinimum", "exclusiveMaximum"):
            for flag in (True, False):
                with self.subTest(key=key, flag=flag):
                    self.refused(one(type="number", **{key: flag}), "draft-4 boolean exclusive bounds")


class TighterBoundTests(unittest.TestCase):
    SCHEMA = {"properties": {
        "lo_excl": {"type": "number", "minimum": 0, "exclusiveMinimum": 1, "x-cli": "--lo-excl"},
        "lo_incl": {"type": "number", "minimum": 2, "exclusiveMinimum": 1, "x-cli": "--lo-incl"},
        "hi_excl": {"type": "number", "maximum": 5, "exclusiveMaximum": 3, "x-cli": "--hi-excl"},
        "hi_incl": {"type": "number", "maximum": 3, "exclusiveMaximum": 5, "x-cli": "--hi-incl"},
        "tie_lo": {"type": "integer", "minimum": 1, "exclusiveMinimum": 1, "x-cli": "--tie-lo"},
        "tie_hi": {"type": "integer", "maximum": 1, "exclusiveMaximum": 1, "x-cli": "--tie-hi"},
    }}

    def test_the_tighter_bound_wins_at_each_end(self) -> None:
        cases = [
            ("--lo-excl", "1", False), ("--lo-excl", "1.5", True),
            ("--lo-incl", "1.5", False), ("--lo-incl", "2", True),
            ("--hi-excl", "3", False), ("--hi-excl", "2.9", True),
            ("--hi-incl", "3.1", False), ("--hi-incl", "3", True),
            ("--tie-lo", "1", False), ("--tie-lo", "2", True),
            ("--tie-hi", "1", False), ("--tie-hi", "0", True),
        ]
        for flag, value, accepted in cases:
            with self.subTest(flag=flag, value=value):
                result = Harness(schema=self.SCHEMA).run([flag, value])
                self.assertEqual(result.exit_code, 0 if accepted else 2, result.output)


class FieldTests(unittest.TestCase):
    def test_nested_properties_map_to_json_pointers_with_rfc_6901_escapes(self) -> None:
        schema = {"properties": {
            "a": {"properties": {"b": {"type": "number", "x-cli": "--a-b"}}},
            "x/y": {"type": "number", "x-cli": "--xy"},
            "m~n": {"type": "number", "x-cli": "--mn"},
        }}
        pointers = {f.name: f.pointer for f in cli_mod.fields(schema)}
        self.assertEqual(pointers, {"a_b": "/a/b", "xy": "/x~1y", "mn": "/m~0n"})

    def test_the_module_imports_and_lists_fields_without_click(self) -> None:
        with mock.patch.dict(sys.modules, {"click": None}):
            module = load_fresh("cad_record_cli_noclick", CLI_PATH)
            self.assertEqual([f.name for f in module.fields(SCHEMA)][:2], ["count", "rank"])


class SourceTests(unittest.TestCase):
    def test_the_cli_layer_holds_only_command_line_values_with_their_flag(self) -> None:
        harness = Harness()
        harness.run(["--count", "2", "--mesh-tol", "0.2"], env={"CAD_BAND": "3"})
        self.assertEqual(harness.layer.values, {"count": 2, "mesh": {"tol": 0.2}})
        self.assertEqual(harness.layer.sources, {"/count": "cli:--count", "/mesh/tol": "cli:--mesh-tol"})

    def test_cli_env_and_default_each_report_their_source_after_resolve(self) -> None:
        harness = Harness()
        result = harness.run(["--count", "2"], env={"CAD_BAND": "3"})
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(harness.resolved.sources["/count"], "cli:--count")
        self.assertEqual(harness.resolved.sources["/band"], "env:CAD_BAND")
        self.assertEqual(harness.resolved.sources["/mesh/tol"], "default")
        self.assertEqual(harness.resolved.values["band"], 3.0)

    def test_the_command_line_beats_the_env_var(self) -> None:
        harness = Harness()
        harness.run(["--mesh-band", "4"], env={"CAD_BAND": "3"})
        self.assertEqual(harness.resolved.sources["/band"], "cli:--mesh-band")
        self.assertEqual(harness.resolved.values["band"], 4.0)

    def test_default_map_comes_from_the_loaded_values_and_is_not_a_cli_source(self) -> None:
        config = loader.Config({"band": 7.0, "mesh": {"tol": 0.5}}, {"/band": "file:cfg.yaml", "/mesh/tol": "file:cfg.yaml"})
        harness = Harness()
        result = harness.run([], config=config)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual((harness.params["mesh_band"], harness.params["mesh_tol"]), (7.0, 0.5))
        self.assertEqual(harness.layer.sources, {})
        self.assertEqual(harness.resolved.sources["/band"], "file:cfg.yaml")


class EscapedPointerTests(unittest.TestCase):
    SCHEMA = {"properties": {
        "x/y": {"type": "number", "default": 1.0, "x-cli": "--slash"},
        "m~n": {"type": "number", "default": 2.0, "x-cli": "--tilde"},
        "grp": {"properties": {"a/b": {"type": "number", "x-cli": "--nested-slash"}}},
    }}

    def test_fields_with_slash_and_tilde_names_resolve_end_to_end(self) -> None:
        harness = Harness(schema=self.SCHEMA)
        result = harness.run(["--slash", "5", "--nested-slash", "7"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(harness.layer.sources, {"/x~1y": "cli:--slash", "/grp/a~1b": "cli:--nested-slash"})
        self.assertEqual(harness.resolved.values, {"x/y": 5.0, "m~n": 2.0, "grp": {"a/b": 7.0}})
        self.assertEqual(harness.resolved.sources["/m~0n"], "default")
        self.assertEqual(harness.resolved.sources["/x~1y"], "cli:--slash")


class ReportTests(unittest.TestCase):
    ERROR = {"message": "band must be below 10", "pointer": "/band", "source": "file:cfg.yaml", "value": 11}

    def failing(self, *errors: dict[str, Any]) -> Any:
        def merge(config: Any, layer: Any) -> Any:
            raise loader.ConfigError(errors)

        return SimpleNamespace(**{**vars(loader), "merge": merge})

    def findings(self, *errors: dict[str, Any]) -> list[dict[str, Any]]:
        result = Harness(self.failing(*errors)).run([])
        self.assertEqual(result.exit_code, 2)
        document = json.loads(result.stdout)
        self.assertEqual(set(document), {"schema", "status", "findings", "payload"})
        self.assertEqual(document["status"], "fail")
        return document["findings"]

    def test_a_config_error_exits_2_with_a_config_invalid_finding_per_error(self) -> None:
        found = self.findings(self.ERROR)
        self.assertEqual(found, [{"code": "config.invalid", "severity": "error", **self.ERROR}])

    def test_a_missing_required_key_gives_a_finding_without_a_value_key(self) -> None:
        error = {"message": "count is required", "pointer": "/count", "source": "default"}
        self.assertNotIn("value", self.findings(error)[0])

    def test_an_explicit_null_gives_value_none(self) -> None:
        error = {"message": "count must be an integer", "pointer": "/count", "source": "file:cfg.yaml", "value": None}
        found = self.findings(error)[0]
        self.assertIn("value", found)
        self.assertIsNone(found["value"])

    def test_a_root_level_error_keeps_the_empty_pointer(self) -> None:
        error = {"message": "config must be an object", "pointer": "", "source": "file:cfg.yaml", "value": []}
        self.assertEqual(self.findings(error)[0]["pointer"], "")

    def test_several_errors_keep_the_loaders_order(self) -> None:
        errors = [
            {"message": "root", "pointer": "", "source": "user"},
            {"message": "a low", "pointer": "/band", "source": "user", "value": 1},
            {"message": "b high", "pointer": "/band", "source": "user", "value": 1},
            {"message": "c", "pointer": "/count", "source": "user", "value": 0},
        ]
        found = self.findings(*errors)
        self.assertEqual([(f["pointer"], f["message"]) for f in found],
                         [("", "root"), ("/band", "a low"), ("/band", "b high"), ("/count", "c")])

    def test_the_stand_in_error_is_a_sorted_tuple_of_mappings_as_the_loader_contract_says(self) -> None:
        error = loader.ConfigError([{"message": "z", "pointer": "/b", "source": "user"},
                                    {"message": "a", "pointer": "/a", "source": "user"}])
        self.assertIsInstance(error.errors, tuple)
        self.assertEqual([e["pointer"] for e in error.errors], ["/a", "/b"])

    def test_plausibility_warnings_enter_the_envelope_findings_unchanged_and_in_order(self) -> None:
        first = {"message": "band is large", "pointer": "/band", "code": "plausibility.band", "source": "cli:--mesh-band",
                 "severity": "warning", "value": 9.9}
        second = {"code": "plausibility.count", "severity": "warning", "message": "count is large",
                  "pointer": "/count", "value": 5, "source": "user"}
        config = loader.Config({"band": 9.9}, {"/band": "user"}, (first, second))
        result = cli_mod.with_warnings({"status": "pass", "findings": [{"code": "x"}]}, config)
        found = emit.envelope(result)["findings"]
        self.assertEqual(found, [first, second, {"code": "x"}])
        self.assertIs(found[0], first)
        self.assertEqual(list(found[0]), list(first))
        self.assertEqual(list(found[1]), list(second))


if __name__ == "__main__":
    unittest.main()
