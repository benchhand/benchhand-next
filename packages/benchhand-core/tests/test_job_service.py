"""The job service: start, progress, status, result, cancellation and reaping, with real processes."""

from __future__ import annotations

import json
import signal
import threading
from pathlib import Path

import pytest
from benchhand_core.jobs import JobError, JobNotSucceeded, JobService, JobSpec, UnknownJob
from benchhand_core.jobs.schema import validate_handle, validate_record
from conftest import Pids
from job_support import FAMILY, LEAVER, LINGERER, python, wait_until

pytestmark = pytest.mark.usefixtures("waitid_variant")
STARTUP_SECONDS = 120.0


def finished(service: JobService, job_id: str) -> dict:
    assert wait_until(lambda: service.status(job_id)["status"] not in ("queued", "running"), STARTUP_SECONDS)
    return service.status(job_id)


def test_start_records_a_running_job_in_its_own_group(service: JobService, project: Path, pids: Pids) -> None:
    marker = project / "pids"
    handle = service.start(JobSpec("kernel/build", python(FAMILY, str(marker))))
    child, _ = pids.family(marker)
    validate_handle(handle)
    assert (handle["status"], handle["kind"]) == ("running", "kernel/build")
    path = project / ".benchhand" / "runs" / f"{handle['jobId']}.json"
    assert path.parent.resolve() == (project / ".benchhand" / "runs").resolve()
    record = json.loads(path.read_text())
    validate_record(record)
    leader = record["process"]["pid"]
    assert record["owner"]["pid"] == __import__("os").getpid()
    assert __import__("os").getpgid(child) == leader  # its own process group, led by the supervisor
    assert (path.parent / ".gitignore").read_text() == "*\n"


def test_a_job_that_exits_zero_succeeds_with_its_result(service: JobService, project: Path) -> None:
    code = "import os; open(os.environ['BENCHHAND_JOB_RESULT'], 'w').write('{\"ok\": true}')"
    handle = service.start(JobSpec("kernel/build", python(code)))
    done = finished(service, handle["jobId"])
    assert (done["status"], done["exitCode"], done["error"]) == ("succeeded", 0, None)
    assert done["finishedAt"] is not None
    result = service.result(handle["jobId"])
    assert json.loads(result.read_text()) == {"ok": True}
    assert done["resultPath"] == str(result)


def test_a_result_path_can_be_chosen(service: JobService, project: Path) -> None:
    target = project / "out" / "answer.txt"
    target.parent.mkdir()
    code = "import os; open(os.environ['BENCHHAND_JOB_RESULT'], 'w').write('42')"
    handle = service.start(JobSpec("kernel/build", python(code), result_path=target))
    finished(service, handle["jobId"])
    assert service.result(handle["jobId"]) == target.resolve()


def test_success_without_a_result_file_has_no_result_path(service: JobService) -> None:
    handle = service.start(JobSpec("kernel/build", python("pass")))
    assert finished(service, handle["jobId"])["resultPath"] is None
    with pytest.raises(JobNotSucceeded):
        service.result(handle["jobId"])


def test_a_job_that_exits_nonzero_or_dies_of_a_signal_fails(service: JobService) -> None:
    failing = service.start(JobSpec("kernel/build", python("import sys; sys.exit(3)")))
    done = finished(service, failing["jobId"])
    assert (done["status"], done["exitCode"], done["error"]) == ("failed", 3, "the job exited with status 3")
    killed = service.start(
        JobSpec("kernel/build", python("import os, signal; os.kill(os.getpid(), signal.SIGUSR1)"))
    )
    done = finished(service, killed["jobId"])
    assert (done["status"], done["exitCode"]) == ("failed", -signal.SIGUSR1)
    with pytest.raises(JobNotSucceeded):
        service.result(failing["jobId"])


def test_output_goes_to_the_log_not_to_the_service(service: JobService) -> None:
    handle = service.start(
        JobSpec("kernel/build", python("import sys; print('out'); print('err', file=sys.stderr)"))
    )
    done = finished(service, handle["jobId"])
    assert sorted(Path(done["logPath"]).read_text().split()) == ["err", "out"]


def test_progress_is_recorded_while_running_and_dropped_after(service: JobService, project: Path) -> None:
    handle = service.start(JobSpec("kernel/build", python("import time; time.sleep(600)")))
    job_id = handle["jobId"]
    assert handle["progress"] == {"fraction": None, "message": None}
    service.report_progress(job_id, fraction=0.25, message="building")
    assert service.report_progress(job_id, fraction=0.5)["progress"] == {
        "fraction": 0.5,
        "message": "building",
    }
    assert service.status(job_id)["progress"] == {"fraction": 0.5, "message": "building"}
    with pytest.raises(ValueError):
        service.report_progress(job_id, fraction=1.5)
    with pytest.raises(ValueError):
        service.report_progress(job_id, message="x" * 501)
    service.cancel(job_id)
    assert service.report_progress(job_id, fraction=0.9)["progress"]["fraction"] == 0.5
    with pytest.raises(UnknownJob):
        service.report_progress("nonexistent", fraction=0.1)


def test_cancel_kills_a_family_that_ignores_sigterm(service: JobService, project: Path, pids: Pids) -> None:
    marker = project / "pids"
    handle = service.start(JobSpec("collision/sweep", python(FAMILY, str(marker))))
    child, grandchild = pids.family(marker)
    cancelled = service.cancel(handle["jobId"])
    assert (cancelled["status"], cancelled["exitCode"]) == ("cancelled", -signal.SIGKILL)
    pids.assert_gone(child, grandchild)
    assert service.cancel(handle["jobId"]) == cancelled  # idempotent
    assert service.status(handle["jobId"])["status"] == "cancelled"


def test_cancel_of_a_job_that_ended_keeps_its_status(service: JobService) -> None:
    handle = service.start(JobSpec("kernel/build", python("pass")))
    done = finished(service, handle["jobId"])
    assert service.cancel(handle["jobId"]) == done
    assert done["status"] == "succeeded"


def test_a_process_left_behind_by_a_finished_job_is_killed(
    service: JobService, project: Path, pids: Pids
) -> None:
    marker = project / "grandchild"
    handle = service.start(JobSpec("kernel/build", python(LEAVER, str(marker))))
    assert finished(service, handle["jobId"])["status"] == "succeeded"
    grandchild = int(marker.read_text())
    pids.known.append(grandchild)
    pids.assert_gone(grandchild)


def test_a_group_that_outlives_its_command_is_killed_on_cancel(
    service: JobService, project: Path, pids: Pids
) -> None:
    marker = project / "pids"
    handle = service.start(JobSpec("kernel/build", python(LINGERER, str(marker))))
    child, grandchild = pids.family(marker)
    service.cancel(handle["jobId"])
    pids.assert_gone(child, grandchild)


def test_reap_finishes_ended_jobs_without_being_asked_about_them(service: JobService) -> None:
    handle = service.start(JobSpec("kernel/build", python("pass")))
    assert (
        wait_until(lambda: service.reap(), STARTUP_SECONDS)
        or service.status(handle["jobId"])["status"] != "running"
    )
    assert service.status(handle["jobId"])["status"] == "succeeded"


def test_closing_the_service_cancels_running_jobs(project: Path, pids: Pids) -> None:
    marker = project / "pids"
    with JobService(project, grace_seconds=0.2) as service:
        handle = service.start(JobSpec("kernel/build", python(FAMILY, str(marker))))
        child, grandchild = pids.family(marker)
    pids.assert_gone(child, grandchild)
    assert JobService(project).status(handle["jobId"])["status"] == "cancelled"


def test_list_jobs_and_unknown_ids(service: JobService) -> None:
    first = service.start(JobSpec("kernel/build", python("pass")))
    second = service.start(JobSpec("kernel/build", python("pass")))
    assert {h["jobId"] for h in service.list_jobs()} == {first["jobId"], second["jobId"]}
    with pytest.raises(UnknownJob):
        service.status("nonexistent")


def test_concurrent_starts_get_distinct_records(service: JobService, project: Path) -> None:
    handles: list[dict] = []

    def start() -> None:
        handles.append(service.start(JobSpec("kernel/build", python("pass"))))

    threads = [threading.Thread(target=start) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len({h["jobId"] for h in handles}) == 6
    assert len(list((project / ".benchhand" / "runs").glob("*.json"))) == 6


def test_a_program_that_cannot_start_leaves_no_record(service: JobService, project: Path) -> None:
    with pytest.raises(FileNotFoundError):
        service.start(JobSpec("kernel/build", ["benchhand-no-such-program"]))
    assert list((project / ".benchhand" / "runs").glob("*.json")) == []
    assert list((project / ".benchhand" / "runs").glob("*.log")) == []


def test_a_job_needs_a_valid_kind_and_a_command(service: JobService, project: Path) -> None:
    with pytest.raises(Exception, match="Render"):
        service.start(JobSpec("Render", python("pass")))
    with pytest.raises(ValueError):
        service.start(JobSpec("kernel/build", []))
    assert list((project / ".benchhand" / "runs").glob("*.json")) == []


def test_a_job_it_does_not_own_cannot_be_cancelled_while_its_owner_runs(
    service: JobService, project: Path
) -> None:
    handle = service.start(JobSpec("kernel/build", python("import time; time.sleep(600)")))
    other = JobService(project)
    with pytest.raises(JobError, match="owned by process"):
        other.cancel(handle["jobId"])
    assert other.recovery.removed == ()
