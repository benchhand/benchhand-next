#!/usr/bin/env python3
"""review_render.render's readiness waits, against stand-ins for ocp_viewer, Playwright and the viewer
process: no FreeCAD, kernel or browser runs. The page logs the viewer's connection after a delay, the
canvas changes before it settles, and a canvas that never settles times out."""

from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any, Callable
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_render.py"
_spec = importlib.util.spec_from_file_location("cad_design_review_render", SCRIPT)
assert _spec and _spec.loader
rr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rr)

VIEWS = {"iso": ((1.0, 0.0, 0.0), (0.0, 0.0, 0.0), 1.0), "base": ((0.0, 1.0, 0.0), (0.0, 0.0, 0.0), 2.0)}


class Clock:
    """time.monotonic for render: it moves only when the page waits."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class Message:
    def __init__(self, text: str) -> None:
        self.text = text


class Page:
    """A Playwright page whose console logs `console` after goto() and whose canvas shows `frames`
    in turn, one per screenshot. `events` records the order of goto, connection and show calls."""

    def __init__(self, clock: Clock, console: list[str], frames: dict[str, list[bytes]], events: list[str]) -> None:
        self.clock, self.console, self.frames, self.events = clock, console, frames, events
        self.showing = "splash"
        self.shots: list[bytes] = []

    def expect_console_message(self, predicate: Callable[[Message], bool], timeout: float) -> Any:
        page = self

        class Waiter:
            def __enter__(self) -> None:
                return None

            def __exit__(self, kind: Any, error: Any, trace: Any) -> bool:
                if kind is not None:
                    return False
                for text in page.console:  # each message arrives one second later than the one before
                    page.clock.now += 1.0
                    if page.clock.now * 1000 > timeout:
                        break
                    if predicate(Message(text)):
                        page.events.append("connected")
                        return False
                raise TimeoutError(f"no matching console message within {timeout} ms")

        return Waiter()

    def goto(self, url: str, wait_until: str) -> None:
        self.events.append("goto")

    def wait_for_selector(self, selector: str) -> None:
        assert selector == "canvas"

    def wait_for_timeout(self, ms: float) -> None:
        self.clock.now += ms / 1000

    @property
    def canvas(self) -> Any:
        page = self

        class Canvas:
            def screenshot(self) -> bytes:
                frames = page.frames[page.showing]
                shot = frames.pop(0) if len(frames) > 1 else frames[0]
                page.shots.append(shot)
                return shot

        return Canvas()

    def locator(self, selector: str) -> Any:
        assert selector == "canvas"
        return types.SimpleNamespace(first=self.canvas)


class RenderWaits(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cad-review-render-")
        self.addCleanup(temporary.cleanup)
        self.out = Path(temporary.name)
        self.clock = Clock()
        self.events: list[str] = []
        self.closed: list[str] = []

    def render(self, console: list[str], frames: dict[str, list[bytes]]) -> tuple[dict[str, Any], Page]:
        page = Page(self.clock, console, frames, self.events)
        views = iter(VIEWS)

        def show(*shapes: Any, **options: Any) -> None:
            page.showing = next(views)
            self.events.append(f"show {page.showing}")

        browser = mock.Mock(new_page=mock.Mock(return_value=page), close=lambda: self.closed.append("browser"))
        playwright = mock.Mock(chromium=mock.Mock(launch=mock.Mock(return_value=browser)))
        manager = mock.MagicMock()
        manager.__enter__.return_value = playwright
        viewer = mock.Mock(pid=4242, poll=mock.Mock(return_value=None),
                           terminate=lambda: self.closed.append("viewer"), wait=mock.Mock(return_value=0))
        modules = {"ocp_viewer": types.SimpleNamespace(Camera=types.SimpleNamespace(RESET="reset"), show=show),
                   "playwright": types.ModuleType("playwright"),
                   "playwright.sync_api": types.SimpleNamespace(sync_playwright=lambda: manager)}
        args = argparse.Namespace(out=self.out, kernels=["build123d"], parts_root=self.out / "parts",
                                  hw=self.out / "hw", pose="nominal", port=4000)
        with mock.patch.dict(sys.modules, modules), \
                mock.patch.object(rr, "load_module", return_value=object()), \
                mock.patch.object(rr.subprocess, "Popen", return_value=viewer), \
                mock.patch.object(rr, "port_open", side_effect=[True, False]), \
                mock.patch.object(rr, "scene", return_value=([], [], [], {})), \
                mock.patch.object(rr, "views", return_value=VIEWS), \
                mock.patch.object(rr.time, "monotonic", self.clock.monotonic):
            return rr.render(args), page

    def test_nothing_is_shown_until_the_page_logs_the_viewer_connection(self) -> None:
        console = ["Handling message", "Attempt #1 to reconnect in 1s", rr.VIEWER_CONNECTED]
        frames = {"splash": [b"splash"], "iso": [b"iso"], "base": [b"base"]}
        report, _page = self.render(console, frames)
        self.assertEqual(self.events, ["goto", "connected", "show iso", "show base"])
        self.assertEqual(sorted(report["pngs"]["build123d"]), ["base", "iso"])

    def test_each_view_saves_the_frame_it_settled_on(self) -> None:
        frames = {"splash": [b"logo", b"splash", b"splash"],
                  "iso": [b"splash", b"iso-half", b"iso-drawn", b"iso"], "base": [b"iso", b"base-half", b"base"]}
        report, page = self.render([rr.VIEWER_CONNECTED], frames)
        saved = {view: Path(path).read_bytes() for view, path in report["pngs"]["build123d"].items()}
        self.assertEqual(saved, {"iso": b"iso", "base": b"base"})
        self.assertEqual(page.shots, [b"logo", b"splash", b"splash", b"splash", b"iso-half", b"iso-drawn", b"iso",
                                      b"iso", b"iso", b"base-half", b"base", b"base"])

    def test_a_canvas_that_never_settles_times_out_and_stops_the_browser_and_viewer(self) -> None:
        changing = [f"frame {n}".encode() for n in range(1000)]
        frames = {"splash": [b"splash"], "iso": changing, "base": [b"base"]}
        with self.assertRaisesRegex(RuntimeError, "did not settle on a new frame within 60 s"):
            self.render([rr.VIEWER_CONNECTED], frames)
        self.assertNotIn("show base", self.events)
        self.assertEqual(self.closed, ["browser", "viewer"])

    def test_a_viewer_that_never_connects_times_out_before_anything_is_shown(self) -> None:
        with self.assertRaises(TimeoutError):
            self.render(["Handling message"] * 200, {"splash": [b"splash"]})
        self.assertEqual(self.events, ["goto"])
        self.assertEqual(self.closed, ["browser", "viewer"])


if __name__ == "__main__":
    unittest.main()
