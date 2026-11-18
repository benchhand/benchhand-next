#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""fail_fast.py: the scope plan, the fail-fast read order, stopping the producers still running at
the first blocking result, the exit-status mapping and strays. Producers are fakes on a fake clock."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from modload import load_module as load  # noqa: E402

fail_fast = load("cad_record_fail_fast", Path(__file__).resolve().parents[1] / "scripts" / "fail_fast.py")

ARGV = {ident: (ident, "--version", "v1") for ident in fail_fast.STEP_ORDER if ident != "validate"}
STRAY = {"record": "hw/.cad/runs/r.json", "state": "orphaned", "stop": ["kill -TERM -- -42"]}


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class Producer:
    """A fake producer that ends with `code` once the clock reaches `ends`. With `None` it does not end by itself."""

    def __init__(self, clock: Clock, code: int, ends: float | None) -> None:
        self.clock, self.code, self.ends = clock, code, ends
        self.stopped_while_running = False
        self.stops = 0

    def ended(self) -> bool:
        return self.ends is not None and self.clock() >= self.ends

    def stop(self) -> int:
        self.stops += 1
        if not self.ended():
            self.stopped_while_running = True
            return -15
        return self.code

    def result(self) -> Any:
        return {"status": {0: "pass", 1: "fail"}.get(self.code, "error")}


class Run:
    """One execute call with fake producers: `behavior` maps a step id to (exit code, end time)."""

    def __init__(self, behaviour: dict[str, tuple[int, float | None]], validate: int = 0,
                 strays: list[list[dict[str, Any]]] | None = None) -> None:
        self.clock = Clock()
        self.behaviour = behaviour
        self.validate_code = validate
        self.started: list[str] = []
        self.producers: dict[str, Producer] = {}
        self.stray_answers = list(strays or [])

    def spawn(self, step: Any) -> Producer:
        code, ends = self.behaviour[step.id]
        self.started.append(step.id)
        self.producers[step.id] = Producer(self.clock, code, ends)
        return self.producers[step.id]

    def strays(self) -> list[dict[str, Any]]:
        return self.stray_answers.pop(0) if self.stray_answers else []

    def __call__(self, work: Any, **options: Any) -> Any:
        return fail_fast.execute(work, validate=lambda: (self.validate_code, {"findings": []}), spawn=self.spawn,
                                 strays=self.strays, clock=self.clock, sleep=self.clock.sleep, **options)


def statuses(outcome: Any) -> dict[str, str]:
    return {step.id: step.status for step in outcome.steps}


COMMIT = {"validate": "R", "form": "C", "static.changed": "R", "sweep.smoke": "R", "render": "O", "static.all": "-"}


class Planning(unittest.TestCase):
    def test_a_scope_runs_its_r_steps_and_its_c_steps_only_when_stale_in_fail_fast_order(self) -> None:
        cases = {"nothing stale": ((), True), "form stale": (("form",), False)}
        for label, (stale, skipped) in cases.items():
            with self.subTest(label):
                work = fail_fast.plan("commit", dict(reversed(COMMIT.items())), ARGV, stale=stale)
                self.assertEqual([step.id for step in work.steps], ["validate", "form", "static.changed", "sweep.smoke"])
                self.assertEqual(work.steps[1].skip is not None, skipped)
                self.assertEqual((work.steps[0].argv, work.steps[2].argv), (None, ARGV["static.changed"]))
                self.assertFalse(work.sequential)

    def test_a_step_that_does_not_apply_is_skipped_with_its_reason(self) -> None:
        work = fail_fast.plan("commit", COMMIT, ARGV, not_applicable={"sweep.smoke": "no independent movable joint"})
        self.assertEqual(work.steps[-1].skip, "no independent movable joint")

    def test_the_full_scope_is_sequential(self) -> None:
        self.assertTrue(fail_fast.plan("full", {"validate": "R", "static.all": "R"}, ARGV).sequential)

    def test_an_unknown_scope_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown scope"):
            fail_fast.plan("nightly", COMMIT, ARGV)


PARALLEL = fail_fast.Plan("commit", False, (fail_fast.Step("validate"), *(fail_fast.Step(i, ARGV[i]) for i in
                                                                         ("form", "static.changed", "sweep.smoke"))))
SEQUENTIAL = fail_fast.Plan("full", True, (fail_fast.Step("validate"), *(fail_fast.Step(i, ARGV[i]) for i in
                                                                         ("form", "static.all", "sweep.full"))))


class Execution(unittest.TestCase):
    def test_every_step_passing_passes_and_reports_each_in_plan_order(self) -> None:
        run = Run({"form": (0, 3.0), "static.changed": (0, 1.0), "sweep.smoke": (0, 2.0)})
        outcome = run(PARALLEL)
        self.assertEqual((outcome.status, outcome.exit, outcome.stopped_at), ("pass", 0, None))
        self.assertEqual([step.id for step in outcome.steps], ["validate", "form", "static.changed", "sweep.smoke"])
        self.assertEqual(sorted(run.started), ["form", "static.changed", "sweep.smoke"], "all start at once")
        self.assertAlmostEqual(outcome.steps[2].seconds, 1.0, delta=0.1, msg="its own end, not when it was read")

    def test_results_are_read_in_plan_order_so_the_first_blocking_step_in_order_stops_the_run(self) -> None:
        run = Run({"form": (1, 3.0), "static.changed": (1, 1.0), "sweep.smoke": (0, None)})
        outcome = run(PARALLEL)
        self.assertEqual((outcome.status, outcome.stopped_at), ("fail", "form"),
                         "static.changed failed first in time, but form comes first in the read order")
        self.assertEqual(statuses(outcome), {"validate": "pass", "form": "fail", "static.changed": "fail",
                                             "sweep.smoke": "stopped"})

    def test_the_first_blocking_result_terminates_every_later_producer_still_running(self) -> None:
        run = Run({"form": (1, 1.0), "static.changed": (0, None), "sweep.smoke": (0, None)})
        outcome = run(PARALLEL)
        self.assertEqual(outcome.stopped_at, "form")
        self.assertEqual({i: (p.stopped_while_running, p.stops) for i, p in run.producers.items()},
                         {"form": (False, 1), "static.changed": (True, 1), "sweep.smoke": (True, 1)})
        self.assertEqual([(s.status, s.exit) for s in outcome.steps[2:]], [("stopped", -15), ("stopped", -15)])

    def test_the_full_scope_starts_each_producer_after_the_one_before_passed(self) -> None:
        run = Run({"form": (0, 1.0), "static.all": (1, 2.0), "sweep.full": (0, 3.0)})
        outcome = run(SEQUENTIAL)
        self.assertEqual(run.started, ["form", "static.all"], "the sweep never starts after a failed static check")
        self.assertEqual(statuses(outcome)["sweep.full"], "stopped")
        self.assertEqual((outcome.status, outcome.exit, outcome.stopped_at), ("fail", 1, "static.all"))

    def test_a_failed_validation_starts_no_producer(self) -> None:
        run = Run({"form": (0, 1.0), "static.changed": (0, 1.0), "sweep.smoke": (0, 1.0)}, validate=1)
        outcome = run(PARALLEL)
        self.assertEqual((run.started, outcome.status, outcome.stopped_at), ([], "fail", "validate"))
        self.assertEqual(set(statuses(outcome).values()) - {"fail"}, {"stopped"})

    def test_exit_statuses_other_than_0_and_1_are_no_result_and_exit_2(self) -> None:
        for code in (2, 127, -9):
            with self.subTest(code):
                outcome = Run({"form": (code, 1.0), "static.changed": (0, 1.0), "sweep.smoke": (0, 1.0)})(PARALLEL)
                self.assertEqual((outcome.steps[1].status, outcome.status, outcome.exit), ("no_result", "no_result", 2))

    def test_a_judge_decides_a_producer_status_from_its_exit_and_result_and_the_exit_is_kept(self) -> None:
        def judge(step: Any, code: int | None, result: Any) -> str:
            return "pass" if step.id == "form" else fail_fast.status_of(code)

        outcome = Run({"form": (1, 1.0), "static.changed": (0, 1.0), "sweep.smoke": (0, 1.0)})(PARALLEL, judge=judge)
        self.assertEqual((outcome.steps[1].status, outcome.steps[1].exit, outcome.status), ("pass", 1, "pass"))

    def test_a_producer_that_cannot_start_is_no_result(self) -> None:
        run = Run({"static.changed": (0, 1.0), "sweep.smoke": (0, 1.0)})
        spawn = run.spawn

        def failing(step: Any) -> Producer:
            if step.id == "form":
                raise FileNotFoundError(2, "No such file", "uv")
            return spawn(step)

        run.spawn = failing  # type: ignore[method-assign]
        outcome = run(PARALLEL)
        self.assertEqual((outcome.steps[1].status, outcome.exit, outcome.stopped_at), ("no_result", 2, "form"))
        self.assertIn("cannot start", outcome.steps[1].result["error"])

    def test_strays_before_the_run_start_nothing_and_after_it_void_the_result(self) -> None:
        before = Run({"form": (0, 1.0), "static.changed": (0, 1.0), "sweep.smoke": (0, 1.0)}, strays=[[STRAY]])
        outcome = before(PARALLEL)
        self.assertEqual((before.started, outcome.status, outcome.exit, outcome.strays), ([], "no_result", 2, (STRAY,)))
        after = Run({"form": (0, 1.0), "static.changed": (0, 1.0), "sweep.smoke": (0, 1.0)}, strays=[[], [STRAY]])
        outcome = after(PARALLEL)
        self.assertEqual((len(after.started), outcome.status, outcome.exit), (3, "no_result", 2))
        self.assertEqual(set(statuses(outcome).values()), {"pass"}, "every step passed; the leftover voids the run")


if __name__ == "__main__":
    unittest.main()
