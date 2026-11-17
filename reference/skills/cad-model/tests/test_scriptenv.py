#!/usr/bin/env python3
"""cadmodel.scriptenv: PEP 723 header reading and the shared-environment launch command.

Run: python3 -m unittest discover -s cad/skills/cad-model/tests -p test_scriptenv.py -v
Standard library only; the real setup.py regression test requires uv.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS))
from cadmodel import build, scriptenv  # noqa: E402 - stdlib-only imports

RUN_SPEC = importlib.util.spec_from_file_location("cad_run", SKILLS / "cad-flow" / "scripts" / "run.py")
assert RUN_SPEC is not None and RUN_SPEC.loader is not None
run = importlib.util.module_from_spec(RUN_SPEC)
RUN_SPEC.loader.exec_module(run)

HEADER = """#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "cadquery==2.8.0",
#     "cadquery-ocp==7.9.3.1.1",
#     "PyYAML>=6.0",
# ]
# ///
\"\"\"A runner.\"\"\"
"""


class ScriptEnvTests(unittest.TestCase):
    def script(self, text: str) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "run_kernel.py"
        path.write_text(text, encoding="utf-8")
        return path

    def test_setup_py_uses_inline_requirements_and_preserves_script_path(self) -> None:
        script = self.script(HEADER).with_name("setup.py")
        script.write_text(HEADER + "print('setup ran')\n", encoding="utf-8")
        command = scriptenv.script_command(script, "--flag", uv="/bin/uv")
        self.assertEqual([command[index + 1] for index, item in enumerate(command[:-1]) if item == "--with"],
                         ["cadquery==2.8.0", "cadquery-ocp==7.9.3.1.1", "PyYAML>=6.0"])
        self.assertEqual(command[-3:], ["python", str(script), "--flag"])

    def test_setup_py_runs_with_uv_using_its_inline_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "setup.py"
            script.write_text('# /// script\n# dependencies = []\n# ///\nprint("setup ran")\n', encoding="utf-8")
            result = subprocess.run(scriptenv.script_command(script), capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "setup ran")

    def test_run_launcher_passes_setup_py_through_the_shared_environment(self) -> None:
        target = SKILLS / "cad-flow" / "scripts" / "setup.py"
        expected = scriptenv.script_command(target, "--yes")
        with patch.object(run.os, "execvp") as execvp:
            self.assertEqual(run.main(["cad-flow/scripts/setup.py", "--yes"]), 0)
        execvp.assert_called_once_with(expected[0], expected)
        self.assertNotIn("--with-requirements", expected)
        self.assertEqual(expected[-3:], ["python", str(target), "--yes"])

    def test_command_passes_the_header_requires_python_and_runs_the_script_with_python(self) -> None:
        script = self.script(HEADER)
        self.assertEqual(scriptenv.script_command(script, "--flag", uv="/bin/uv"),
                         ["/bin/uv", "run", "--quiet", "--isolated", "--no-project", "--python", ">=3.12,<3.13",
                          "--with-requirements", str(script), "python", str(script), "--flag"])

    def test_python_command_runs_code_in_the_same_environment(self) -> None:
        script = self.script(HEADER)
        self.assertEqual(scriptenv.python_command(script, "-c", "pass")[-4:],
                         [str(script), "python", "-c", "pass"])

    def test_a_header_without_requires_python_leaves_the_interpreter_to_uv(self) -> None:
        script = self.script('# /// script\n# dependencies = ["pyyaml>=6.0"]\n# ///\n')
        self.assertNotIn("--python", scriptenv.script_command(script))

    def test_a_script_without_one_header_block_is_rejected(self) -> None:
        for text in ("print('no header')\n", HEADER + HEADER):
            with self.subTest(blocks=text.count("# /// script")), self.assertRaises(ValueError):
                scriptenv.script_command(self.script(text))

    def test_pins_and_dependency_names_come_from_the_header(self) -> None:
        script = self.script(HEADER)
        self.assertEqual(scriptenv.pinned(script, "cadquery_ocp"), "7.9.3.1.1")
        self.assertEqual(scriptenv.dependency_names(script), {"cadquery", "cadquery-ocp", "pyyaml"})
        with self.assertRaises(ValueError):
            scriptenv.pinned(script, "pyyaml")  # a range, not a pin

    def test_the_shipped_kernel_runners_launch_on_their_header_python(self) -> None:
        for kernel, runner in build.RUNNERS.items():
            command = scriptenv.script_command(runner)
            with self.subTest(kernel=kernel):
                requires = command[command.index("--python") + 1]
                self.assertIn(f'# requires-python = "{requires}"\n', runner.read_text(encoding="utf-8"))
                self.assertEqual(command[command.index("--with-requirements") + 1], str(runner))


class SharedCacheEnvironmentTests(unittest.TestCase):
    """cad-model and cad-motion scripts share cached results only when their envs match."""

    # This class holds the pin. A move to another Python or numpy changes these constants and the headers.
    PYTHON = ">=3.12,<3.15"
    RUNNER_PYTHON = ">=3.12,<3.13"   # the kernel runners and their test doubles stay on the Python of their sealed results
    # Only these scripts may declare RUNNER_PYTHON. The doubles run in the cadquery runner's environment.
    RUNNER_SCRIPTS = frozenset({
        "cad-model/scripts/run_cadquery.py", "cad-model/scripts/run_build123d.py",
        "cad-model/tests/fixtures/run_cadquery_breaking_submit.py",
        "cad-model/tests/fixtures/run_cadquery_reusing_workers.py",
    })
    NUMPY = "numpy==2.5.5"

    def headers(self) -> dict[Path, dict]:
        found = {}
        for skill in ("cad-model", "cad-motion"):
            for folder in (SKILLS / skill / "scripts", SKILLS / skill / "tests" / "fixtures"):
                for script in sorted(folder.glob("*.py")):
                    try:
                        found[script] = scriptenv.metadata(script)
                    except ValueError:
                        continue  # no PEP 723 block: not a script env
        return found

    def drifted(self, found: dict[str, str | None]) -> dict[str, str | None]:
        """The scripts whose requires-python is not the one this class allows them."""
        return {name: value for name, value in found.items()
                if value != (self.RUNNER_PYTHON if name in self.RUNNER_SCRIPTS else self.PYTHON)}

    def test_every_script_header_of_both_skills_declares_one_python(self) -> None:
        scripts = self.headers()
        names = {script.name for script in scripts}
        self.assertTrue({"cad_model.py", "run_cadquery.py", "motion.py", "mesh_probe.py"} <= names, sorted(names))
        found = {str(script.relative_to(SKILLS)): meta.get("requires-python") for script, meta in scripts.items()}
        self.assertLessEqual(self.RUNNER_SCRIPTS, set(found))
        self.assertEqual(self.drifted(found), {})

    def test_the_runner_range_is_refused_on_any_unlisted_script(self) -> None:
        runners = {str(runner.relative_to(SKILLS)) for runner in build.RUNNERS.values()}
        self.assertLessEqual(runners, self.RUNNER_SCRIPTS)
        stray = {"cad-motion/scripts/run_something.py": self.RUNNER_PYTHON}
        self.assertEqual(self.drifted(stray), stray)
        self.assertEqual(self.drifted({"cad-model/scripts/run_cadquery.py": self.PYTHON}),
                         {"cad-model/scripts/run_cadquery.py": self.PYTHON})

    def test_every_declared_numpy_is_one_exact_pin(self) -> None:
        pins = {str(script.relative_to(SKILLS)): requirement
                for script, meta in self.headers().items()
                for requirement in meta.get("dependencies", [])
                if scriptenv.normalize(scriptenv.NAME.match(requirement).group("name")) == "numpy"}
        self.assertTrue({"cad-model/scripts/cad_model.py", "cad-motion/tests/fixtures/mesh_probe.py"} <= set(pins), pins)
        self.assertEqual(set(pins.values()), {self.NUMPY}, pins)


if __name__ == "__main__":
    unittest.main()
