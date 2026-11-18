#!/usr/bin/env python3
"""The cad_model.py command line: how it refuses bad arguments and where its options reach the output.

Run: python3 -m unittest discover -s skills/cad-model/tests -p test_cli_surface.py -v
Needs `uv`. None of these commands builds a part, so none waits on a kernel environment.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
CLI = SCRIPTS / "cad_model.py"
COMMANDS = ("run", "check", "diff", "latest", "store")


@unittest.skipUnless(shutil.which("uv"), "uv is required to start the script")
class CliSurfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-cli-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "hw").mkdir()

    def cli(self, *args: str, output: str = "json") -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "CAD_OUTPUT": output}
        return subprocess.run(["uv", "run", "--quiet", "--script", str(CLI), *args], capture_output=True,
                              text=True, check=False, cwd=self.root, env=env)

    def test_help_exits_zero_for_the_tool_and_every_command(self) -> None:
        for args in ((), *((command,) for command in COMMANDS)):
            with self.subTest(command=args):
                proc = self.cli(*args, "--help")
                self.assertEqual((proc.returncode, "Usage" in proc.stdout or "usage" in proc.stdout),
                                 (0, True), proc.stderr[-1000:])

    def test_no_command_and_an_unknown_command_are_usage_errors(self) -> None:
        for args in ((), ("frobnicate",)):
            with self.subTest(args=args):
                proc = self.cli(*args)
                self.assertEqual((proc.returncode, proc.stdout), (2, ""), proc.stderr[-1000:])

    def test_a_missing_required_argument_or_option_is_a_usage_error(self) -> None:
        for args in (("run", "hw"), ("latest", "--label", "v1"), ("check",), ("diff", "v1"), ("store", "hw")):
            with self.subTest(args=args):
                self.assertEqual(self.cli(*args).returncode, 2)

    def test_a_value_outside_its_choices_is_a_usage_error(self) -> None:
        for args in (("run", "hw", "--label", "v1", "--kernel", "freecad"), ("store", "purge", "hw")):
            with self.subTest(args=args):
                self.assertEqual(self.cli(*args).returncode, 2)

    def test_a_malformed_option_value_is_a_usage_error(self) -> None:
        for flag, value in (("--pair", "TST-0001"), ("--pair", "TST-0001:TST-0001"), ("--expect-solids", "TST-0001"),
                            ("--allow-interference", "nonsense"), ("--jobs", "0"), ("--jobs", "many")):
            with self.subTest(flag=flag, value=value):
                proc = self.cli("check", "v1", "--hw", "hw", flag, value)
                self.assertEqual((proc.returncode, proc.stdout), (2, ""), proc.stderr[-1000:])

    def test_options_that_exclude_each_other_or_need_another_are_usage_errors(self) -> None:
        for extra in (("--pair", "TST-0001:TST-0002", "--changed-only"), ("--cache", "c", "--no-cache"),
                      ("--since-version", "v1")):
            with self.subTest(extra=extra):
                proc = self.cli("check", "v2", "--hw", "hw", *extra)
                self.assertEqual((proc.returncode, proc.stdout), (2, ""), proc.stderr[-1000:])

    def test_json_prints_the_full_result_whatever_cad_output_says(self) -> None:
        args = ("store", "gc", "hw", "--dry-run")
        full = self.cli(*args, output="json")
        compact = self.cli(*args, output="compact")
        forced = self.cli(*args, "--json", output="compact")
        self.assertEqual((full.returncode, compact.returncode, forced.returncode), (0, 0, 0), forced.stderr[-1000:])
        self.assertEqual(json.loads(forced.stdout), json.loads(full.stdout))
        self.assertEqual(json.loads(full.stdout)["payload"]["dry_run"], True)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(compact.stdout)


class MainCase(unittest.TestCase):
    """`main(argv)` in this process: what it accepts, what it refuses, and what it hands on, with recorders for the builders.

    Needs no uv and no kernel: the part builder, check, diff and store are stand-ins that note their arguments."""

    def setUp(self) -> None:
        patched_path = mock.patch.object(sys, "path", [str(SCRIPTS), *sys.path])
        patched_path.start()
        self.addCleanup(patched_path.stop)
        spec = importlib.util.spec_from_file_location("cad_model_under_test", CLI)
        assert spec is not None and spec.loader is not None
        self.cad = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cad)
        from cadmodel import build, motion

        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self.emitted: list[dict[str, object]] = []

        def recorder(name: str) -> object:
            def record(*args: object, **kwargs: object) -> tuple[int, dict[str, object]]:
                self.calls.append((name, args, kwargs))
                return 0, {"label": "v1"}

            return record

        for name in ("run", "store_gc", "reconcile_latest"):
            self.start(mock.patch.object(build, name, recorder(name)))
        self.start(mock.patch.object(build, "version_dir", lambda hw, label: None))
        fakes = {"cadmodel.check": types.SimpleNamespace(check=recorder("check")),
                 "cadmodel.diff": types.SimpleNamespace(diff=recorder("diff"))}
        self.start(mock.patch.dict(sys.modules, fakes))
        self.start(mock.patch.object(self.cad.load_lifecycle(), "claim_run", lambda *a, **k: contextlib.nullcontext()))
        self.start(mock.patch.object(motion.load_pose(), "stdout_to_stderr", contextlib.nullcontext))
        self.start(mock.patch.object(self.cad.emit, "emit", lambda result, **kwargs: self.emitted.append(kwargs)))
        self.motion = motion
        temporary = tempfile.TemporaryDirectory(prefix="cad-main-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def start(self, patcher: "mock._patch[object]") -> None:
        patcher.start()
        self.addCleanup(patcher.stop)

    def main(self, *argv: str) -> tuple[int, str, str]:
        self.calls.clear()
        self.emitted.clear()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.cad.main(list(argv))
            except SystemExit as stop:
                code = stop.code if isinstance(stop.code, int) else 0
        return code, out.getvalue(), err.getvalue()

    def refused(self, *argv: str) -> None:
        code, out, err = self.main(*argv)
        self.assertEqual((code, out, self.calls), (2, "", []), err[-1000:])

    def forwarded(self, *argv: str) -> tuple[str, tuple[object, ...], dict[str, object]]:
        code, _, err = self.main(*argv)
        self.assertEqual(code, 0, err[-1000:])
        self.assertEqual(len(self.calls), 1, self.calls)
        return self.calls[0]


class MainTests(MainCase):
    def test_a_value_taking_option_refuses_a_following_option_as_its_value(self) -> None:
        for argv in (("run", "hw", "--label", "--json"), ("run", "hw", "--label", "v1", "--attach", "--json"),
                     ("check", "v1", "--out", "--json"), ("check", "v1", "--cache", "--no-cache"),
                     ("check", "v1", "--hw", "--exact"), ("check", "v1", "--pair", "--exact"),
                     ("check", "v1", "--allow-interference", "--exact"), ("check", "v1", "--expect-solids", "--exact"),
                     ("check", "v1", "--jobs", "--exact"), ("check", "v2", "--changed-only", "--since-version", "--exact"),
                     ("diff", "v1", "v2", "--out", "--json"), ("diff", "v1", "v2", "--hw", "--json"),
                     ("latest", "hw", "--label", "--json"), ("run", "hw", "--label", "v1", "--kernel", "--json")):
            with self.subTest(argv=argv):
                self.refused(*argv)

    def test_a_value_that_argparse_takes_as_a_value_is_one(self) -> None:
        for flag_value, expected in (("-1", "-1"), ("-0.5", "-0.5"), ("-", "-"), ("-a b", "-a b")):
            with self.subTest(label=flag_value):
                _, args, _ = self.forwarded("latest", "hw", "--label", flag_value)
                self.assertEqual(args, (Path("hw"), expected))

    def test_the_equals_form_takes_an_option_like_value(self) -> None:
        self.forwarded("diff", "v1", "v2", "--out=--json")
        self.assertEqual(self.emitted[0]["out"], Path("--json"))

    def test_the_equals_form_of_a_registered_option_takes_a_value_with_a_space(self) -> None:
        self.forwarded("diff", "v1", "v2", "--out=my report.json")
        self.assertEqual(self.emitted[0]["out"], Path("my report.json"))
        _, args, _ = self.forwarded("diff", "v1", "v2", "--hw=my hw")
        self.assertEqual(args, (Path("my hw"), "v1", "v2"))
        _, args, kwargs = self.forwarded("check", "v1", "--hw=my hw", "--cache=my cache", "--out=my report.json")
        self.assertEqual((args[0], args[5], self.emitted[0]["out"]), (Path("my hw"), Path("my cache"),
                                                                       Path("my report.json")))

    def test_a_value_with_a_space_in_a_separate_word_arrives_whole(self) -> None:
        self.forwarded("diff", "v1", "v2", "--out", "my report.json")
        self.assertEqual(self.emitted[0]["out"], Path("my report.json"))
        _, args, _ = self.forwarded("check", "v1", "--hw", "my hw", "--cache", "my cache")
        self.assertEqual((args[0], args[5]), (Path("my hw"), Path("my cache")))

    def test_an_equals_word_with_an_unregistered_name_is_not_an_option_value(self) -> None:
        for argv in (("diff", "v1", "v2", "--bogus=a b"), ("diff", "v1", "v2", "--bogus=ab")):
            with self.subTest(argv=argv):
                self.refused(*argv)

    def test_a_numeric_hardware_positional_that_starts_with_a_dash_is_a_path(self) -> None:
        _, args, _ = self.forwarded("run", "-5", "--label", "v1")
        self.assertEqual(args[0], Path("-5"))

    def test_a_positional_that_starts_with_a_dash_and_holds_a_space_is_a_path(self) -> None:
        for argv, expected in ((("run", "-alt hw", "--label", "v1"), (Path("-alt hw"), "v1", "auto", [])),
                               (("latest", "-a b", "--label", "v1"), (Path("-a b"), "v1")),
                               (("store", "gc", "-ab hw"), (Path("-ab hw"), False))):
            with self.subTest(argv=argv):
                _, args, _ = self.forwarded(*argv)
                self.assertEqual(args, expected)
        _, args, _ = self.forwarded("diff", "-a b", "-c d")
        self.assertEqual(args, (Path("hw"), "-a b", "-c d"))

    def test_an_unknown_option_is_a_usage_error(self) -> None:
        for argv in (("run", "hw", "--label", "v1", "--bogus"), ("run", "hw", "--label", "v1", "-x"),
                     ("diff", "v1", "v2", "--hw")):
            with self.subTest(argv=argv):
                self.refused(*argv)

    def test_dash_h_prints_the_help_of_the_tool_and_of_every_command(self) -> None:
        for argv in (("-h",), *((command, "-h") for command in COMMANDS)):
            with self.subTest(argv=argv):
                code, out, _ = self.main(*argv)
                self.assertEqual((code, "sage" in out), (0, True))

    def test_a_leading_double_dash_before_the_command_is_skipped(self) -> None:
        self.assertEqual(self.forwarded("--", "run", "hw", "--label", "v1"),
                         ("run", (Path("hw"), "v1", "auto", []), {}))

    def test_a_double_dash_inside_a_command_ends_its_options(self) -> None:
        _, args, _ = self.forwarded("diff", "--", "v1", "v2")
        self.assertEqual(args, (Path("hw"), "v1", "v2"))

    def test_every_occurrence_of_a_repeated_scalar_option_is_checked_in_order(self) -> None:
        for argv in (("check", "v1", "--jobs", "0", "--jobs", "1"), ("check", "v1", "--jobs", "0", "--help"),
                     ("run", "hw", "--label", "v1", "--kernel", "freecad", "--kernel", "auto"),
                     ("check", "v1", "--jobs=0", "--jobs=2")):
            with self.subTest(argv=argv):
                self.refused(*argv)

    def test_help_ends_parsing_before_a_later_bad_value_or_option(self) -> None:
        for argv in (("check", "v1", "--help", "--jobs", "0"), ("check", "--help", "--bogus"),
                     ("check", "v1", "-h", "--pair", "nonsense")):
            with self.subTest(argv=argv):
                code, out, _ = self.main(*argv)
                self.assertEqual((code, "sage" in out, self.calls), (0, True, []))

    def test_a_converter_that_raises_value_error_is_a_usage_error(self) -> None:
        for flag, value in (("--jobs", "\u00b2"), ("--expect-solids", "TST-0001=\u00b2")):
            with self.subTest(flag=flag):
                self.refused("check", "v1", flag, value)

    def test_an_interrupt_propagates_as_a_keyboard_interrupt(self) -> None:
        with mock.patch.object(self.motion, "load_pose", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.cad.main(["latest", "hw", "--label", "v1"])

    def test_a_path_the_process_cannot_read_is_still_a_path(self) -> None:
        write_only = self.root / "write-only"
        write_only.mkdir()
        write_only.chmod(stat.S_IWUSR | stat.S_IXUSR)
        self.addCleanup(write_only.chmod, stat.S_IRWXU)
        target = str(write_only)
        for argv in (("latest", target, "--label", "v1"), ("check", "v1", "--hw", target),
                     ("check", "v1", "--hw", "hw", "--cache", target), ("diff", "v1", "v2", "--out", target)):
            with self.subTest(argv=argv):
                self.forwarded(*argv)

    def test_run_forwards_its_defaults_and_its_repeated_attachments_in_order(self) -> None:
        self.assertEqual(self.forwarded("run", "hw", "--label", "v1"),
                         ("run", (Path("hw"), "v1", "auto", []), {}))
        self.forwarded("run", "--attach", "TST-0001=TST-0002", "hw", "--attach", "@a=@b", "--label", "v2",
                       "--kernel", "cadquery")
        self.assertEqual(self.calls[0][1], (Path("hw"), "v2", "cadquery", ["TST-0001=TST-0002", "@a=@b"]))

    def test_check_forwards_its_defaults(self) -> None:
        hw = self.root / "hw"
        name, args, kwargs = self.forwarded("check", "v1", "--hw", str(hw))
        self.assertEqual((name, args, kwargs), (
            "check", (hw, "v1", None, [], {}, hw.resolve() / ".cad", 1),
            {"exact": False, "changed_only": False, "since": None}))
        self.assertEqual(self.emitted[0]["out"], None)
        self.assertEqual(self.emitted[0]["json_flag"], False)

    def test_check_forwards_repeated_options_interleaved_with_its_positional(self) -> None:
        hw, cache = self.root / "hw", self.root / "cache"
        _, args, kwargs = self.forwarded(
            "check", "--pair", "TST-0001:TST-0002", "v2", "--hw", str(hw), "--pair", "TST-0002:TST-0003",
            "--allow-interference", "TST-0001:TST-0003", "--allow-interference", "TST-0002:TST-0004",
            "--expect-solids", "TST-0001=2", "--expect-solids", "TST-0002=3", "--exact", "--jobs", "4",
            "--cache", str(cache), "--out", str(self.root / "r.json"), "--json")
        self.assertEqual(args, (hw, "v2", [("TST-0001", "TST-0002"), ("TST-0002", "TST-0003")],
                                [("TST-0001", "TST-0003"), ("TST-0002", "TST-0004")],
                                {"TST-0001": 2, "TST-0002": 3}, cache, 4))
        self.assertEqual(kwargs, {"exact": True, "changed_only": False, "since": None})
        self.assertEqual((self.emitted[0]["out"], self.emitted[0]["json_flag"]), (self.root / "r.json", True))

    def test_check_forwards_a_changed_only_selection_without_a_cache(self) -> None:
        _, args, kwargs = self.forwarded("check", "v3", "--hw", "hw", "--changed-only", "--since-version", "v1",
                                         "--no-cache", "--jobs", "auto")
        self.assertEqual((args[5], args[6] >= 1, kwargs), (None, True, {"exact": False, "changed_only": True,
                                                                          "since": "v1"}))

    def test_diff_latest_and_store_forward_their_arguments(self) -> None:
        self.assertEqual(self.forwarded("diff", "--hw", "alt", "v1", "--out", "o.json", "v2"),
                         ("diff", (Path("alt"), "v1", "v2"), {}))
        self.assertEqual(self.emitted[0]["out"], Path("o.json"))
        self.assertEqual(self.forwarded("latest", "--label", "v4", "hw"), ("reconcile_latest", (Path("hw"), "v4"), {}))
        self.assertEqual(self.forwarded("store", "--dry-run", "gc", "hw"), ("store_gc", (Path("hw"), True), {}))
        self.assertEqual(self.forwarded("store", "gc", "hw"), ("store_gc", (Path("hw"), False), {}))


class DeliberateChangeTests(MainCase):
    """The changes the Click conversion makes on purpose. These FAIL on the argparse script and pass on the Click one."""

    def test_an_abbreviated_option_is_a_usage_error(self) -> None:
        for argv in (("store", "gc", "hw", "--dry-r"), ("run", "hw", "--lab", "v1"), ("check", "v1", "--exa")):
            with self.subTest(argv=argv):
                self.refused(*argv)

    def test_help_wins_over_a_conflict_or_a_bad_choice_in_the_same_command_line(self) -> None:
        for argv in (("check", "v1", "--cache", "c", "--no-cache", "--help"), ("store", "purge", "hw", "--help")):
            with self.subTest(argv=argv):
                code, out, _ = self.main(*argv)
                self.assertEqual((code, "sage" in out, self.calls), (0, True, []))

    def test_an_unknown_top_level_option_is_a_usage_error_beside_help(self) -> None:
        for argv in (("--help", "--bogus"), ("--bogus", "--help")):
            with self.subTest(argv=argv):
                code, out, _ = self.main(*argv)
                self.assertEqual((code, out, self.calls), (2, "", []))


if __name__ == "__main__":
    unittest.main()
