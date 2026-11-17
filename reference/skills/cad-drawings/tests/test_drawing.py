#!/usr/bin/env python3
"""Focused layout, FreeCAD discovery and export-reading tests; part drawings are in test_part_drawings.py."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from defusedxml import ElementTree as SafeET

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/drawing.py"
sys.path.insert(0, str(SCRIPT.parent))
import freecad_runtime  # noqa: E402
import sheet_export  # noqa: E402
from layout_check import Box, SheetRegions, check_layout  # noqa: E402

FREECADCMD = freecad_runtime.find_freecadcmd()
FREECAD_PRESENT = FREECADCMD is not None and FREECADCMD.is_file()
# Qt writes the PDF page size in whole points: ISO A4 landscape and ANSI A landscape.
PAGE_POINTS = {"iso": (842.0, 595.0), "asme": (792.0, 612.0)}

REGIONS = SheetRegions(frame=Box(10, 10, 190, 140), title_block=Box(100, 110, 190, 140), symbol_cell=Box(170, 110, 190, 120))
SYMBOL = '<g id="projection-symbol"><circle cx="180" cy="115" r="3"/></g>'


def svg_document(*parts: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 150">{"".join(parts)}</svg>'


def view(name: str, x0: float, y0: float, x1: float, y1: float) -> str:
    return f'<g id="view-{name}"><path d="M {x0} {y0} L {x1} {y0} L {x1} {y1} L {x0} {y1} Z"/></g>'


def annotations(*parts: str) -> str:
    return f'<g id="cad-annotations">{"".join(parts)}</g>'


def label(content: str, x: float, y: float, size: float = 3.5, **extra: str) -> str:
    attributes = "".join(f' {key.replace("_", "-")}="{value}"' for key, value in extra.items())
    return f'<text x="{x}" y="{y}" font-size="{size}"{attributes}>{content}</text>'


class LayoutCheck(unittest.TestCase):
    """check_layout over hand-built SVG: one passing sheet, then one violation per rule."""

    def good_sheet(self, *extra: str, symbol: str = SYMBOL) -> str:
        return svg_document(view("front", 30, 40, 90, 60), view("top", 30, 75, 90, 85), symbol,
                            annotations('<g class="dimension"><line x1="30" y1="34" x2="90" y2="34"/>'
                                        + label("60.00", 60, 33, text_anchor="middle") + "</g>"), *extra)

    def test_clean_layout_passes(self) -> None:
        self.assertEqual(check_layout(self.good_sheet(), REGIONS, ["DN"]), [])

    def test_overlapping_views_fail(self) -> None:
        problems = check_layout(self.good_sheet(view("right", 85, 45, 100, 55)), REGIONS, [])
        self.assertTrue(any("view-front and view-right" in p for p in problems), problems)

    def test_views_closer_than_minimum_gap_fail(self) -> None:
        problems = check_layout(self.good_sheet(view("right", 95, 40, 105, 60)), REGIONS, [])
        self.assertTrue(any("5.00 mm apart" in p for p in problems), problems)

    def test_view_outside_frame_or_on_title_block_fails(self) -> None:
        problems = check_layout(self.good_sheet(view("right", 150, 100, 170, 125)), REGIONS, [])
        self.assertIn("view-right overlaps the title block", problems)
        problems = check_layout(self.good_sheet(view("right", 2, 40, 20, 60)), REGIONS, [])
        self.assertIn("view-right lies outside the drawing frame", problems)

    def test_annotation_text_over_geometry_fails(self) -> None:
        problems = check_layout(self.good_sheet(annotations(label("21.00", 85, 50))), REGIONS, [])
        self.assertTrue(any("'21.00' overlaps view-front geometry" in p for p in problems), problems)

    def test_rotated_annotation_text_uses_its_rotated_extent(self) -> None:
        clear = annotations(label("21.00", 97, 50, text_anchor="middle", transform="rotate(-90 97 50)"))
        self.assertEqual(check_layout(self.good_sheet(clear), REGIONS, []), [])
        crossing = annotations(label("21.00", 92, 50, text_anchor="middle", transform="rotate(-90 92 50)"))
        self.assertTrue(any("overlaps view-front" in p for p in check_layout(self.good_sheet(crossing), REGIONS, [])))

    def test_annotation_text_overlapping_text_or_frame_fails(self) -> None:
        problems = check_layout(self.good_sheet(annotations(label("⌀5.01", 55, 33))), REGIONS, [])
        self.assertTrue(any("'⌀5.01'" in p and "'60.00'" in p and "overlaps" in p for p in problems), problems)
        problems = check_layout(self.good_sheet(annotations(label("⌀5.01", 8, 30))), REGIONS, [])
        self.assertTrue(any("crosses the drawing frame" in p for p in problems), problems)

    def test_dimension_line_through_geometry_fails(self) -> None:
        crossing = annotations('<g class="dimension"><line x1="95" y1="40" x2="85" y2="60"/></g>')
        problems = check_layout(self.good_sheet(crossing), REGIONS, [])
        self.assertTrue(any("dimension line" in p and "view-front" in p for p in problems), problems)
        leader = annotations('<g class="leader"><line x1="95" y1="30" x2="60" y2="50"/></g>')
        self.assertEqual(check_layout(self.good_sheet(leader), REGIONS, []), [])

    def test_projection_symbol_outside_its_cell_or_duplicated_fails(self) -> None:
        outside = '<g id="projection-symbol"><circle cx="195" cy="115" r="3"/></g>'
        self.assertIn("projection symbol lies outside its title-block cell",
                      check_layout(self.good_sheet(symbol=outside), REGIONS, []))
        problems = check_layout(self.good_sheet(SYMBOL), REGIONS, [])
        self.assertIn("expected exactly one projection symbol, found 2", problems)

    def test_template_placeholder_fails(self) -> None:
        problems = check_layout(self.good_sheet(label("A. Nemesis", 120, 130)), REGIONS, ["A. Nemesis"])
        self.assertIn("template placeholder remains: 'A. Nemesis'", problems)



class FreeCADDiscovery(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cad-freecad-lookup-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def executable(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def test_set_freecadcmd_is_used_as_given(self) -> None:
        on_path = self.executable(self.root / "bin" / "freecadcmd")
        environ = {"FREECADCMD": str(self.root / "missing"), "PATH": str(on_path.parent)}
        self.assertEqual(freecad_runtime.find_freecadcmd(environ), self.root / "missing")

    def test_path_lookup_accepts_both_command_names(self) -> None:
        for name in ("freecadcmd", "FreeCADCmd"):
            with self.subTest(name=name):
                command = self.executable(self.root / name / name)
                found = freecad_runtime.find_freecadcmd({"PATH": str(command.parent)})
                self.assertTrue(found is not None and found.samefile(command), found)

    def test_without_path_command_only_the_macos_app_remains(self) -> None:
        app = freecad_runtime.MACOS_FREECADCMD
        found = freecad_runtime.find_freecadcmd({"HOME": str(self.root / "empty-home"), "PATH": str(self.root)})
        self.assertEqual(found, app if app.is_file() else None)

    def test_lookup_uses_authoritative_home_candidate_when_path_omits_it(self) -> None:
        command = self.executable(self.root / ".local" / "bin" / "freecadcmd")
        environ = {"HOME": str(self.root), "PATH": str(self.root / "empty")}
        found = freecad_runtime.find_freecadcmd(environ, platform_name="linux")
        self.assertEqual(found, command)

    def test_templates_follow_a_symlinked_bundle_command(self) -> None:
        command = self.executable(self.root / "squashfs-root" / "usr" / "bin" / "freecadcmd")
        link = self.root / "local" / "bin" / "freecadcmd"
        link.parent.mkdir(parents=True)
        link.symlink_to(command)
        self.assertEqual(freecad_runtime.templates_dir(link),
                         command.resolve().parents[1] / "share" / "Mod" / "TechDraw" / "Templates")

    def test_templates_of_a_bundle_are_listed_on_the_host(self) -> None:
        command = self.executable(self.root / "squashfs-root" / "usr" / "bin" / "freecadcmd")
        templates = command.parents[1] / "share" / "Mod" / "TechDraw" / "Templates"
        (templates / "ISO").mkdir(parents=True)
        (templates / "ISO" / "A4.svg").write_text("<svg/>", encoding="utf-8")
        with patch("fea_solvers.probe", side_effect=AssertionError("a bundle needs no probe")):
            self.assertEqual(freecad_runtime.techdraw_templates(command),
                             (str(templates.resolve()), frozenset({"ISO/A4.svg"})))

    def test_templates_of_a_wrapper_script_are_listed_inside_freecad_while_its_mount_exists(self) -> None:
        # An AppImage's resources live under a /tmp/.mount_* directory that ends with the FreeCAD process,
        # so the probe lists the templates in that process and nothing reads the directory afterwards.
        wrapper = self.executable(self.root / "wrappers" / "freecadcmd")
        gone = self.root / "mount_gone" / "usr" / "share" / "Mod" / "TechDraw" / "Templates"
        report = {"techdraw_templates": {"dir": str(gone), "files": ["ASME/ANSIA_Landscape.svg"]}}
        with patch("fea_solvers.probe", return_value=report) as probe:
            found = freecad_runtime.techdraw_templates(wrapper)
        probe.assert_called_once_with(wrapper)
        self.assertFalse(gone.exists())
        self.assertEqual(found, (str(gone), frozenset({"ASME/ANSIA_Landscape.svg"})))

class FreeCADConcurrency(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cad-freecad-parallel-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_jobs_default_is_bounded_by_cpu_available_memory_and_items(self) -> None:
        with patch.object(freecad_runtime.os, "cpu_count", return_value=8), \
                patch.object(freecad_runtime, "available_memory_bytes", return_value=4_000):
            self.assertEqual(freecad_runtime.jobs_for(None, 10, 1_000), 4)
            self.assertEqual(freecad_runtime.jobs_for(None, 2, 1_000), 2)
            self.assertEqual(freecad_runtime.jobs_for(5, 2, 1_000), 2)

    def test_auto_jobs_ignore_unknown_memory_bound(self) -> None:
        with patch.object(freecad_runtime.os, "cpu_count", return_value=8), \
                patch.object(freecad_runtime, "available_memory_bytes", return_value=0):
            self.assertEqual(freecad_runtime.jobs_for(None, 5, 1_000), 5)

    def test_shared_pool_results_stay_in_input_order(self) -> None:
        with ThreadPoolExecutor(max_workers=3) as executor:
            result = freecad_runtime.map_jobs((0.06, 0.0, 0.03), 3,
                                              lambda delay: (time.sleep(delay), delay)[1], executor)
        self.assertEqual(result, [0.06, 0.0, 0.03])

    def test_freecad_job_environment_is_isolated_and_stdout_is_not_the_summary(self) -> None:
        command = self.root / "fake-freecad"
        command.write_text("#!/bin/sh\nexec python3 \"$1\"\n", encoding="utf-8")
        command.chmod(0o755)
        script = self.root / "job.py"
        script.write_text("import json, os\n"
                          "job = json.load(open(os.environ['CAD_DRAWING_JOB']))\n"
                          "keys = ('HOME', 'FREECAD_USER_HOME', 'FREECAD_USER_DATA', 'FREECAD_USER_TEMP', "
                          "'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_RUNTIME_DIR', 'TMPDIR')\n"
                          "json.dump({'status': 'pass', 'environment': {k: os.environ[k] for k in keys}, "
                          "'directories_exist': all(os.path.isdir(os.environ[k]) for k in keys)}, "
                          "open(job['result'], 'w'))\n"
                          "print('diagnostic output')\n", encoding="utf-8")
        with ThreadPoolExecutor(max_workers=2) as executor:
            values = freecad_runtime.map_jobs((1, 2), 2,
                                              lambda _: freecad_runtime.run_job(command, script, {}, self.root, 10)[0],
                                              executor)
        self.assertTrue(all(value and value["directories_exist"] for value in values))
        first, second = (value["environment"] for value in values if value)
        self.assertTrue(all(first[key] != second[key] for key in first))
    def fake_freecad(self, script_text: str) -> tuple[Path, Path]:
        command = self.root / "fake-freecad"
        command.write_text("#!/bin/sh\nexec python3 \"$1\"\n", encoding="utf-8")
        command.chmod(0o755)
        script = self.root / "job.py"
        script.write_text(script_text, encoding="utf-8")
        return command, script

    def test_a_failed_job_reports_its_error_with_its_traceback(self) -> None:
        command, script = self.fake_freecad("import json, os\njob = json.load(open(os.environ['CAD_DRAWING_JOB']))\n"
                                            "json.dump({'status': 'error', 'error': 'probe failed', "
                                            "'traceback': 'Traceback (most recent call last):\\n  boom'}, "
                                            "open(job['result'], 'w'))\n")
        result, reason = freecad_runtime.run_job(command, script, {}, self.root, 10)
        self.assertIsNone(result)
        self.assertTrue(reason.startswith("probe failed"), reason)
        self.assertIn("Traceback (most recent call last):\n  boom", reason)

    def test_a_job_without_a_result_reports_its_stdout_and_stderr(self) -> None:
        command, script = self.fake_freecad("import sys\nprint('stdout tail')\nprint('stderr tail', file=sys.stderr)\n"
                                            "sys.exit(3)\n")
        result, reason = freecad_runtime.run_job(command, script, {}, self.root, 10)
        self.assertIsNone(result)
        for text in ("exit 3", "stdout tail", "stderr tail"):
            self.assertIn(text, reason)

    def test_a_job_gets_the_given_environment_with_its_isolation(self) -> None:
        command, script = self.fake_freecad("import json, os\njob = json.load(open(os.environ['CAD_DRAWING_JOB']))\n"
                                            "json.dump({'status': 'pass', 'mark': os.environ.get('CAD_TEST_MARK'), "
                                            "'home': os.environ['HOME']}, open(job['result'], 'w'))\n")
        result, _ = freecad_runtime.run_job(command, script, {}, self.root, 10,
                                            environ={**os.environ, "CAD_TEST_MARK": "given", "HOME": "/nowhere"})
        assert result is not None
        self.assertEqual(result["mark"], "given")
        self.assertNotEqual(result["home"], "/nowhere")

    def test_a_group_that_ends_on_sigterm_gets_no_sigkill(self) -> None:
        import subprocess
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True,
                                   text=True)
        with patch.object(freecad_runtime.os, "killpg", wraps=os.killpg) as killpg:
            freecad_runtime._terminate_process_group(process)
        self.assertEqual([call.args for call in killpg.call_args_list if call.args[1] != 0],
                         [(process.pid, signal.SIGTERM)])
        self.assertIsNotNone(process.poll())

    def test_a_child_that_ignores_sigterm_dies_after_its_leader_exits(self) -> None:
        import subprocess
        child = ("import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); "
                 "time.sleep(60)")
        leader = (f"import subprocess, sys, time; c = subprocess.Popen([sys.executable, '-c', {child!r}], "
                  "stdout=subprocess.PIPE, text=True); c.stdout.readline(); print(c.pid, flush=True); time.sleep(60)")
        process = subprocess.Popen([sys.executable, "-c", leader], start_new_session=True, stdout=subprocess.PIPE,
                                   text=True)
        assert process.stdout is not None
        pid = int(process.stdout.readline())
        freecad_runtime._terminate_process_group(process)
        process.stdout.close()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_a_group_owned_by_another_user_is_not_an_error(self) -> None:
        import subprocess
        process = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True, text=True)
        process.wait()
        with patch.object(freecad_runtime.os, "killpg", side_effect=PermissionError):
            freecad_runtime._terminate_process_group(process)
            freecad_runtime._terminate_active_processes((process,))

    def test_sigterm_terminates_and_reaps_every_process_group(self) -> None:
        command = self.root / "fake-freecad"
        command.write_text("#!/bin/sh\nexec python3 \"$1\"\n", encoding="utf-8")
        command.chmod(0o755)
        script = self.root / "job.py"
        script.write_text("import json, os, signal, time\n"
                          "job = json.load(open(os.environ['CAD_DRAWING_JOB']))\n"
                          "open(job['result'] + '.pid', 'w').write(str(os.getpid()))\n"
                          "signal.signal(signal.SIGTERM, lambda *_: time.sleep(60))\n"
                          "time.sleep(60)\n", encoding="utf-8")
        with self.assertRaises(freecad_runtime.JobInterrupted):
            with freecad_runtime.terminate_jobs_on_signal():
                with ThreadPoolExecutor(max_workers=2) as executor:
                    [executor.submit(freecad_runtime.run_job, command, script, {}, self.root, 120) for _ in range(2)]
                    deadline = time.monotonic() + 10
                    while len(list(self.root.glob("*.result.json.pid"))) < 2 and time.monotonic() < deadline:
                        time.sleep(0.05)
                    self.assertEqual(len(list(self.root.glob("*.result.json.pid"))), 2)
                    os.kill(os.getpid(), signal.SIGTERM)

class EpochCli(unittest.TestCase):
    """An oversized SOURCE_DATE_EPOCH stops each producer with a structured error before any FreeCAD job."""

    SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="cad-epoch-cli-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.marker = self.root / "freecad-launched"
        fake = self.root / "freecadcmd"
        fake.write_text(f"#!/bin/sh\necho launched >> '{self.marker}'\n", encoding="utf-8")
        fake.chmod(0o755)
        self.fake = fake

    def run_cli(self, script: str, *args: str, epoch: str) -> tuple[int, dict]:
        env = {**os.environ, "FREECADCMD": str(self.fake), "SOURCE_DATE_EPOCH": epoch}
        proc = subprocess.run([sys.executable, str(self.SCRIPTS / script), str(self.root / "hw"), "--version", "v1", *args],
                              capture_output=True, text=True, env=env, timeout=120)
        try:
            return proc.returncode, json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise AssertionError(f"no JSON from {script} (exit {proc.returncode}): {proc.stderr[-2000:]}") from None

    def test_part_drawing_refuses_an_oversized_epoch(self) -> None:
        code, out = self.run_cli("drawing.py", "--part", "LMP-0005", epoch="9" * 40)
        self.assertEqual((code, out["error"]["code"]), (2, "invalid_source_date_epoch"), out)
        self.assertFalse(self.marker.exists())

    def test_assembly_drawing_refuses_an_oversized_epoch(self) -> None:
        code, out = self.run_cli("assembly_drawing.py", epoch="9" * 40)
        self.assertEqual((code, out["findings"][0]["code"]), (2, "invalid_source_date_epoch"), out)
        self.assertFalse(self.marker.exists())

    def test_a_valid_epoch_is_not_what_stops_either_cli(self) -> None:
        for script, extra in (("drawing.py", ("--part", "LMP-0005")), ("assembly_drawing.py", ())):
            with self.subTest(script=script):
                _, out = self.run_cli(script, *extra, epoch="1700000000")
                self.assertNotIn("invalid_source_date_epoch", json.dumps(out))


class SheetExportParts(unittest.TestCase):
    """Text splitting and PDF reading without FreeCAD; the lamp drawings exercise the Qt export itself."""

    SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="150mm" viewBox="0 0 200 150">'
           '<g style="font-size:3.5px;font-family:osifont;fill:#000000" transform="translate(10 20)">'
           '<text x="5" y="6" text-anchor="middle"><tspan>  Centred\n   label </tspan></text>'
           '<text x="1" y="2"><tspan x="7" y="8" font-weight="bold" font-family="sans-serif, Arial">Moved</tspan></text>'
           '</g><text x="0" y="0" font-size="2" fill="none">hidden</text>'
           '<text x="3" y="4" transform="rotate(-90 3 4)" font-size="2.5" fill="#111">22.00</text>'
           '<path d="M 0 0 L 1 1"/></svg>')

    def test_text_runs_leave_a_text_free_svg(self) -> None:
        root = SafeET.fromstring(self.SVG)
        runs = sheet_export.split_text(root)
        self.assertEqual(root.findall(f".//{sheet_export.TEXT}"), [])
        self.assertEqual(len(root.findall(".//{http://www.w3.org/2000/svg}path")), 1)
        self.assertEqual([run["segments"][0]["text"] for run in runs], ["Centred label", "Moved", "22.00"])
        centred, moved, rotated = runs
        self.assertEqual((centred["x"], centred["y"], centred["anchor"], centred["size"], centred["family"], centred["bold"]),
                         (5.0, 6.0, "middle", 3.5, "osifont", False))
        self.assertEqual(centred["matrix"], [1.0, 0.0, 0.0, 1.0, 10.0, 20.0])
        self.assertEqual((moved["x"], moved["y"], moved["family"], moved["bold"], moved["anchor"]),
                         (7.0, 8.0, "osifont", True, "start"))
        a, b, c, d, e, f = rotated["matrix"]
        apply = lambda x, y: (round(a * x + c * y + e, 9), round(b * x + d * y + f, 9))
        self.assertEqual((apply(3, 4), apply(4, 4)), ((3.0, 4.0), (3.0, 3.0)))
        self.assertEqual((rotated["size"], rotated["fill"]), (2.5, "#111"))

    def test_sheet_size_and_unsized_text_are_checked(self) -> None:
        self.assertEqual(sheet_export.sheet_size_mm(SafeET.fromstring(self.SVG)), (200.0, 150.0))
        letter = SafeET.fromstring('<svg xmlns="http://www.w3.org/2000/svg" width="11in" height="8.5in"/>')
        self.assertAlmostEqual(sheet_export.sheet_size_mm(letter)[1], 215.9)
        with self.assertRaisesRegex(sheet_export.ExportError, "not a length"):
            sheet_export.sheet_size_mm(SafeET.fromstring('<svg xmlns="http://www.w3.org/2000/svg" width="100%"/>'))
        with self.assertRaisesRegex(sheet_export.ExportError, "no font size"):
            sheet_export.split_text(SafeET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><text>bare</text></svg>'))

    def test_qt_style_pdf_text_and_page_size(self) -> None:
        cmap = (b"begincmap\n1 beginbfchar\n<0001> <0041>\nendbfchar\n2 beginbfrange\n<0002> <0003> [<0042> <0009>]\n"
                b"<0004> <0005> <0043>\nendbfrange\nendcmap\n")
        content = zlib.compress(b"BT\n/F5 100 Tf 1 0 0 -1 0 0 Tm\n0 0 Td <0001> Tj\n1 0 Td <0003> Tj\n1 0 Td <0002> Tj\n"
                                b"/Span << /ActualText <> >> BDC\n1 0 Td <0004> Tj\nEMC\nET\nBT\n/F5 100 Tf\n0 0 Td <0005> Tj\nET\n")
        objects = [b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                   b"<< /Type /Page /Parent 2 0 R /Contents 7 0 R /Resources 4 0 R /MediaBox [0 0 842.000000 595.000000] >>",
                   b"<< /Font << /F5 5 0 R >> >>",
                   b"<< /Type /Font /Subtype /Type0 /BaseFont /osifont /ToUnicode 6 0 R>>",
                   b"<< /Length %d >>\nstream\n%sendstream" % (len(cmap), cmap),
                   b"<< /Length %d /Filter /FlateDecode >>\nstream\n%s\nendstream" % (len(content), content)]
        directory = tempfile.TemporaryDirectory(prefix="cad-pdf-read-")
        self.addCleanup(directory.cleanup)
        pdf = Path(directory.name) / "sheet.pdf"
        pdf.write_bytes(b"%PDF-1.4\n" + b"".join(b"%d 0 obj\n%s\nendobj\n" % (number, body)
                                                 for number, body in enumerate(objects, start=2)))
        read = sheet_export.read_pdf(pdf)
        self.assertEqual(read.page_sizes_pt, [(842.0, 595.0)])
        self.assertEqual(read.fonts, ["osifont"])
        self.assertEqual(read.text, "A B\nD")  # tab read as a space; the synthetic-bold repeat skipped
    @unittest.skipUnless(FREECAD_PRESENT, "bundled Osifont test needs FreeCAD 1.1.4 freecadcmd")
    def test_svg_generic_families_are_painted_with_osifont(self) -> None:
        command = freecad_runtime.find_freecadcmd()
        with tempfile.TemporaryDirectory(prefix="cad-font-parity-") as tmp:
            root = Path(tmp)
            svg = root / "input.svg"
            pdf = root / "output.pdf"
            png = root / "output.png"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="150mm" viewBox="0 0 200 150">'
                           '<text x="10" y="20" font-family="sans-serif" font-size="10">Aa 0123</text>'
                           '<text x="10" y="40" font-size="10">⟂∥×−·</text></svg>', encoding="utf-8")
            sheet_export.export_sheet(command, svg, pdf, png, ["Aa 0123"], 300)
            content = sheet_export.read_pdf(pdf)
            runs = sheet_export.split_text(SafeET.fromstring(svg.read_text(encoding="utf-8")))
            self.assertEqual(runs[1]["segments"], [{"vector": character} for character in "⟂∥×−·"])
            self.assertIn('d="M -3 3 H 3 M 0 3 V -3"', runs[1]["vector_markup"]["⟂"])
            self.assertIn('d="M -3 3 H 3 M 0 3 V -3"', runs[1]["vector_markup"]["⊥"])
            self.assertTrue(all(set(run) == {"segments", "vector_advance", "vector_markup", "x", "y", "anchor", "size",
                                              "family", "bold", "fill", "matrix"} for run in runs))
        self.assertEqual(content.text, "Aa 0123")
        self.assertEqual(content.fonts, ["osifont"])
    @staticmethod
    def qt_style_pdf(creation: str = "D:20261116203848+04'00'", xmp: str = "2026-11-16T20:38:48+04:00") -> bytes:
        """A tiny PDF laid out like Qt's: an Info dictionary, plain XMP, an xref table with real offsets."""
        xmp_body = (f'<x:xmpmeta><rdf:Description xmp:CreatorTool="cad-drawings" xmp:CreateDate="{xmp}" '
                    f'xmp:ModifyDate="{xmp}" xmp:MetadataDate="{xmp}"/></x:xmpmeta>').encode()
        bodies = [b"<< /Type /Catalog /Pages 2 0 R /Metadata 4 0 R >>",
                  b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                  b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>",
                  b"<< /Type /Metadata /Subtype /XML /Length %d >>\nstream\n%s\nendstream" % (len(xmp_body), xmp_body),
                  f"<< /Creator (cad-drawings) /CreationDate ({creation}) /ModDate ({creation}) >>".encode()]
        out = bytearray(b"%PDF-1.4\n")
        offsets = []
        for number, body in enumerate(bodies, start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
        start = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(bodies) + 1)
        out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
        out += b"trailer\n<< /Size %d /Root 1 0 R /Info 5 0 R /ID [<aa> <aa>] >>\nstartxref\n%d\n%%%%EOF\n" % (len(bodies) + 1, start)
        return bytes(out)

    @staticmethod
    def assert_xref_intact(test: unittest.TestCase, data: bytes) -> None:
        """Every classic xref entry points at its own object, as a PDF reader needs."""
        start = int(re.search(rb"startxref\s+(\d+)", data).group(1))
        lines = data[start:].split(b"trailer")[0].splitlines()
        count = int(lines[1].split()[1])
        entries = [line for line in lines[2:] if line.endswith(b" n ")]
        test.assertEqual(len(entries), count - 1)
        for number, line in enumerate(entries, start=1):
            test.assertTrue(data[int(line[:10]):].startswith(b"%d 0 obj" % number), (number, line))

    def test_pdf_dates_are_pinned_without_moving_a_byte_offset(self) -> None:
        data = self.qt_style_pdf()
        pinned = sheet_export.pin_pdf_dates(data, 1_700_000_000)   # 2023-11-14 22:13:20 UTC
        self.assertEqual(len(pinned), len(data))
        self.assertEqual(re.findall(rb"/(?:CreationDate|ModDate) \(([^)]*)\)", pinned), [b"D:20231114221320+00'00'"] * 2)
        self.assertEqual(re.findall(rb'xmp:\w+Date="([^"]*)"', pinned), [b"2023-11-14T22:13:20+00:00"] * 3)
        self.assert_xref_intact(self, pinned)
        self.assertEqual(re.sub(rb"20231114221320\+00'00'|2023-11-14T22:13:20\+00:00", b"", pinned).replace(b"D:", b""),
                         re.sub(rb"20261116203848\+04'00'|2026-11-16T20:38:48\+04:00", b"", data).replace(b"D:", b""))

    def test_real_qt_dates_are_pinned_in_their_own_form_at_the_same_length(self) -> None:
        # The strings Qt 6.8.3 wrote on dev (aarch64) and pace (x86_64, the CI runner's build), by TZ. TZ=UTC makes
        # Qt write "Z" in the Info dictionary, which is six bytes shorter than "+00'00'".
        xmp_zone = {"TZ unset": "+00:00", "TZ=UTC": "+00:00", "Europe/Amsterdam": "+01:00", "Asia/Dubai": "+04:00"}
        cases = [
            ("TZ unset", "D:20261117091914+00'00'", "2026-11-17T09:19:14+00:00", "D:20231114221320+00'00'"),
            ("TZ=UTC", "D:20261117091913Z", "2026-11-17T09:19:13+00:00", "D:20231114221320Z"),
            ("Europe/Amsterdam", "D:20261117101855+01'00'", "2026-11-17T10:18:55+01:00", "D:20231114221320+00'00'"),
            ("Asia/Dubai", "D:20261117131856+04'00'", "2026-11-17T13:18:56+04:00", "D:20231114221320+00'00'"),
        ]
        for name, info, xmp, expected_info in cases:
            with self.subTest(tz=name):
                self.assertTrue(xmp.endswith(xmp_zone[name]))
                data = self.qt_style_pdf(info, xmp)
                pinned = sheet_export.pin_pdf_dates(data, 1_700_000_000)
                self.assertEqual(len(pinned), len(data))
                self.assertEqual(re.findall(rb"/(?:CreationDate|ModDate) \(([^)]*)\)", pinned), [expected_info.encode()] * 2)
                self.assertEqual(re.findall(rb'xmp:\w+Date="([^"]*)"', pinned), [b"2023-11-14T22:13:20+00:00"] * 3)
                self.assert_xref_intact(self, pinned)

    def test_pdf_date_grammar_is_pinned_field_for_field(self) -> None:
        pdf_dates = {
            "D:2026": "D:2023", "D:202611": "D:202311", "D:20261117": "D:20231114", "D:2026111709": "D:2023111422",
            "D:202611170918": "D:202311142213", "D:20261117091856": "D:20231114221320",
            "D:20261117091856Z": "D:20231114221320Z", "D:20261117091856+01'00'": "D:20231114221320+00'00'",
            "D:20261117091856-07'30'": "D:20231114221320+00'00'", "D:20261117091856+01'00": "D:20231114221320+00'00",
            "D:20261117091856+0100": "D:20231114221320+0000", "D:20261117091856+01": "D:20231114221320+00",
            "D:20261117091856Z00'00'": "D:20231114221320Z00'00'",
        }
        for original, expected in pdf_dates.items():
            with self.subTest(info=original):
                pinned = sheet_export.pin_pdf_dates(self.qt_style_pdf(original), 1_700_000_000)
                self.assertEqual(re.findall(rb"/(?:CreationDate|ModDate) \(([^)]*)\)", pinned), [expected.encode()] * 2)
                self.assertEqual(len(pinned), len(self.qt_style_pdf(original)))
        xmp_dates = {
            "2026": "2023", "2026-11": "2023-11", "2026-11-17": "2023-11-14", "2026-11-17T09:18Z": "2023-11-14T22:13Z",
            "2026-11-17T09:18:56": "2023-11-14T22:13:20", "2026-11-17T09:18:56Z": "2023-11-14T22:13:20Z",
            "2026-11-17T09:18:56+05:30": "2023-11-14T22:13:20+00:00", "2026-11-17T09:18:56-07:00": "2023-11-14T22:13:20+00:00",
            "2026-11-17T09:18:56.123Z": "2023-11-14T22:13:20.000Z",
            "2026-11-17T09:18:56.123456+01:00": "2023-11-14T22:13:20.000000+00:00",
            "2026-11-17T09:18:56.5": "2023-11-14T22:13:20.0",
        }
        for original, expected in xmp_dates.items():
            with self.subTest(xmp=original):
                data = self.qt_style_pdf(xmp=original)
                pinned = sheet_export.pin_pdf_dates(data, 1_700_000_000)
                self.assertEqual(re.findall(rb'xmp:\w+Date="([^"]*)"', pinned), [expected.encode()] * 3)
                self.assertEqual(len(pinned), len(data))

    def test_a_date_form_that_cannot_keep_its_length_is_refused(self) -> None:
        for original in ("D:2026-11-17", "D:abc", "D:20261117091856X", "D:2026111", "D:20261117091856+01'00'x", "D:"):
            with self.subTest(info=original), self.assertRaisesRegex(sheet_export.ExportError, "PDF date"):
                sheet_export.pin_pdf_dates(self.qt_style_pdf(original), 0)
        for original in ("2026-11-17 09:18:56", "20261117T091856Z", "12026-11-17T09:18:56Z", "2026-11-17T09:18:56.Z", ""):
            with self.subTest(xmp=original), self.assertRaisesRegex(sheet_export.ExportError, "XMP date"):
                sheet_export.pin_pdf_dates(self.qt_style_pdf(xmp=original), 0)

    def test_pinned_dates_do_not_depend_on_the_original_clock_or_zone(self) -> None:
        first = sheet_export.pin_pdf_dates(self.qt_style_pdf(), 0)
        second = sheet_export.pin_pdf_dates(self.qt_style_pdf("D:20300101000000-07'00'", "2030-01-01T00:00:00-07:00"), 0)
        self.assertEqual(first, second)

    def test_pdf_without_a_creation_date_is_refused(self) -> None:
        with self.assertRaisesRegex(sheet_export.ExportError, "CreationDate"):
            sheet_export.pin_pdf_dates(b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\n", 0)

    def test_an_unterminated_date_literal_is_refused_not_left_unpinned(self) -> None:
        whole = self.qt_style_pdf()
        for name in ("CreationDate", "ModDate"):
            with self.subTest(date=name):
                cut = whole.replace(b"/" + name.encode() + b" (D:20261116203848+04'00')",
                                    b"/" + name.encode() + b" (D:20261116203848+04'00'", 1)
                self.assertNotEqual(cut, whole)
                with self.assertRaisesRegex(sheet_export.ExportError, f"unterminated /{name}"):
                    sheet_export.pin_pdf_dates(cut, 0)

    def test_pdf_with_only_a_mod_date_is_refused(self) -> None:
        data = self.qt_style_pdf().replace(b"/CreationDate (D:20261116203848+04'00') ", b"")
        self.assertIn(b"/ModDate", data)
        self.assertNotIn(b"/CreationDate", data)
        with self.assertRaisesRegex(sheet_export.ExportError, "CreationDate"):
            sheet_export.pin_pdf_dates(data, 0)

    def test_pdf_timestamp_follows_source_date_epoch_else_a_fixed_date_never_the_clock(self) -> None:
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1700000000"}):
            self.assertEqual(sheet_export.pdf_timestamp(), 1_700_000_000)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SOURCE_DATE_EPOCH", None)
            with patch.object(time, "time", return_value=1_999_999_999.0):
                self.assertEqual(sheet_export.pdf_timestamp(), sheet_export.DEFAULT_PDF_EPOCH)
        for bad in ("", "yesterday", "-1", "+5", " 5", "1.5", "²", "١٢٣"):
            with self.subTest(value=bad), patch.dict(os.environ, {"SOURCE_DATE_EPOCH": bad}):
                with self.assertRaisesRegex(sheet_export.ExportError, "SOURCE_DATE_EPOCH"):
                    sheet_export.pdf_timestamp()

    def test_source_date_epoch_is_accepted_up_to_the_last_four_digit_year_and_refused_beyond(self) -> None:
        last = 253_402_300_799   # 9999-12-31T23:59:59Z: the PDF date has a four-digit year
        for value, accepted in ((str(last), True), ("0", True), (str(last + 1), False), ("9" * 40, False),
                                ("9" * 5000, False)):
            with self.subTest(digits=len(value), value=value[:14]), patch.dict(os.environ, {"SOURCE_DATE_EPOCH": value}):
                if accepted:
                    self.assertEqual(sheet_export.pdf_timestamp(), int(value))
                else:
                    with self.assertRaisesRegex(sheet_export.ExportError, "SOURCE_DATE_EPOCH"):
                        sheet_export.pdf_timestamp()
        pinned = sheet_export.pin_pdf_dates(self.qt_style_pdf(), last)
        self.assertIn(b"D:99991231235959+00'00'", pinned)
        self.assertEqual(len(pinned), len(self.qt_style_pdf()))
        with self.assertRaisesRegex(sheet_export.ExportError, "epoch"):
            sheet_export.pin_pdf_dates(self.qt_style_pdf(), last + 1)

    def test_a_bad_source_date_epoch_stops_the_export_before_freecad_starts(self) -> None:
        launched: list[str] = []
        with tempfile.TemporaryDirectory(prefix="cad-epoch-") as tmp, \
                patch.object(freecad_runtime, "run_job", lambda *a, **k: launched.append("job") or (None, "")), \
                patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "9" * 40}):
            svg = Path(tmp) / "s.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="150mm">'
                           '<text font-size="5">Aa</text></svg>', encoding="utf-8")
            with self.assertRaisesRegex(sheet_export.ExportError, "SOURCE_DATE_EPOCH"):
                sheet_export.export_sheet(Path("fc"), svg, Path(tmp) / "a.pdf", Path(tmp) / "a.png", ["Aa"], 5)
        self.assertEqual(launched, [])

    def test_part_recipe_names_the_pdf_epoch_so_another_epoch_is_another_recipe(self) -> None:
        import drawing
        context = SimpleNamespace(provenance=lambda pn: {"pn": pn})
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1700000000"}):
            first = drawing.part_recipe(context, "LMP-0005")
            self.assertEqual(first, drawing.part_recipe(context, "LMP-0005"))
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1700003600"}):
            second = drawing.part_recipe(context, "LMP-0005")
        with patch.dict(os.environ):   # restored on exit, so a caller's epoch survives the test
            os.environ.pop("SOURCE_DATE_EPOCH", None)
            default = drawing.part_recipe(context, "LMP-0005")
        self.assertEqual(first["pdf_epoch"], 1_700_000_000)
        self.assertEqual(default["pdf_epoch"], sheet_export.DEFAULT_PDF_EPOCH)
        self.assertEqual(len({json.dumps(r, sort_keys=True) for r in (first, second, default)}), 3)

    def test_document_id_follows_the_sheet_and_is_a_uuid(self) -> None:
        one = sheet_export.document_id(b"<svg>one</svg>", [10.0, 20.0])
        self.assertEqual(one, sheet_export.document_id(b"<svg>one</svg>", [10.0, 20.0]))
        self.assertNotEqual(one, sheet_export.document_id(b"<svg>two</svg>", [10.0, 20.0]))
        self.assertNotEqual(one, sheet_export.document_id(b"<svg>one</svg>", [10.0, 21.0]))
        self.assertRegex(one, r"^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

    @unittest.skipUnless(FREECAD_PRESENT, "PDF reproducibility needs FreeCAD 1.1.4 freecadcmd")
    def test_same_sheet_exports_byte_identical_pdfs(self) -> None:
        command = freecad_runtime.find_freecadcmd()
        with tempfile.TemporaryDirectory(prefix="cad-pdf-repro-") as tmp:
            root = Path(tmp)
            svg = root / "input.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="150mm" viewBox="0 0 200 150">'
                           '<path d="M 10 10 L 100 10 L 100 60 Z" fill="none" stroke="#000"/>'
                           '<text x="10" y="20" font-size="10">Aa 0123</text>'
                           '<text x="10" y="40" font-size="6" font-weight="bold">Bold 456</text>'
                           '<text x="10" y="55" font-size="5">⟂∥ 12.50 H7</text></svg>', encoding="utf-8")
            outputs = []
            with patch.dict(os.environ):   # the default date, whatever epoch the caller has set
                os.environ.pop("SOURCE_DATE_EPOCH", None)
                for name in ("a", "b"):
                    sheet_export.export_sheet(command, svg, root / f"{name}.pdf", root / f"{name}.png", ["Aa 0123"], 300)
                    if name == "a":
                        time.sleep(1.1)   # a wall-clock date would differ by a second
                    outputs.append((root / f"{name}.pdf").read_bytes())
            self.assertEqual(outputs[0], outputs[1])
            self.assert_xref_intact(self, outputs[0])
            with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1700000000"}):
                sheet_export.export_sheet(command, svg, root / "c.pdf", root / "c.png", ["Aa 0123"], 300)
            dated = (root / "c.pdf").read_bytes()
            self.assertRegex(dated, rb"/CreationDate \(D:20231114221320(?:Z|\+00'00')\)")
            self.assertNotEqual(dated, outputs[0])
            svg.write_text(svg.read_text(encoding="utf-8").replace("Aa 0123", "Bb 0123"), encoding="utf-8")
            sheet_export.export_sheet(command, svg, root / "d.pdf", root / "d.png", ["Bb 0123"], 300)
            ids = [re.search(rb"/ID \[ <([0-9a-f]+)>", data).group(1) for data in (outputs[0], (root / "d.pdf").read_bytes())]
            self.assertNotEqual(ids[0], ids[1])

    def test_svg_unknown_glyph_is_rejected(self) -> None:
        root = SafeET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><text font-family="serif" font-size="10">☃</text></svg>')
        with self.assertRaisesRegex(sheet_export.ExportError, "unsupported glyph.*U\\+2603"):
            sheet_export.split_text(root)


if __name__ == "__main__":
    unittest.main()
