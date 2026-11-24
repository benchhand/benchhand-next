"""The job service: start, progress, status, result, cancellation and reaping, with real processes."""

from __future__ import annotations

import json
import os
import signal
import threading
from pathlib import Path

import pytest
from benchhand_contracts.models.jobs.job_schema import JobHandle, JobRecord, JobStatus
from benchhand_core.jobs import JobError, JobNotSucceeded, JobService, JobSpec, UnknownJob
from conftest import Pids
from job_support import FAMILY, LEAVER, LINGERER, python, running, wait_until

STARTUP_SECONDS = 120.0


def finished(service: JobService, job_id: str) -> JobHandle:
    assert wait_until(
        lambda: service.status(job_id).status not in (JobStatus.queued, JobStatus.running), STARTUP_SECONDS
    )
    return service.status(job_id)


def test_start_records_a_running_job_in_its_own_group(service: JobService, project: Path, pids: Pids) -> None:
    marker = project / "pids"
    handle = service.start(JobSpec("kernel/build", python(FAMILY, str(marker))))
    child, _ = pids.family(marker)
    assert (handle.status, handle.kind) == (JobStatus.running, "kernel/build")
    path = project / ".benchhand" / "runs" / f"{handle.job_id}.json"
    record = json.loads(path.read_text())
    supervisor = record["process"]["pid"]
    assert record["owner"]["pid"] == os.getpid()
    assert os.getsid(child) == supervisor  # under the supervisor...
    assert os.getpgid(child) not in (supervisor, os.getpgrp())  # ...in a process group of its own
    assert (path.parent / ".gitignore").read_text() == "*\n"


def test_a_job_that_exits_zero_succeeds_with_its_result(service: JobService, project: Path) -> None:
    code = "import os; open(os.environ['BENCHHAND_JOB_RESULT'], 'w').write('{\"ok\": true}')"
    handle = service.start(JobSpec("kernel/build", python(code)))
    done = finished(service, handle.job_id)
    assert (done.status, done.exit_code, done.error) == (JobStatus.succeeded, 0, None)
    assert done.finished_at is not None
    result = service.result(handle.job_id)
    assert json.loads(result.read_text()) == {"ok": True}
    assert done.result_path == str(result)


def test_a_result_path_can_be_chosen(service: JobService, project: Path) -> None:
    target = project / "out" / "answer.txt"
    target.parent.mkdir()
    code = "import os; open(os.environ['BENCHHAND_JOB_RESULT'], 'w').write('42')"
    handle = service.start(JobSpec("kernel/build", python(code), result_path=target))
    finished(service, handle.job_id)
    assert service.result(handle.job_id) == target.resolve()


def test_success_without_a_result_file_has_no_result_path(service: JobService) -> None:
    handle = service.start(JobSpec("kernel/build", python("pass")))
    assert finished(service, handle.job_id).result_path is None
    with pytest.raises(JobNotSucceeded):
        service.result(handle.job_id)


def test_a_job_that_exits_nonzero_or_dies_of_a_signal_fails(service: JobService) -> None:
    failing = service.start(JobSpec("kernel/build", python("import sys; sys.exit(3)")))
    done = finished(service, failing.job_id)
    assert (done.status, done.exit_code, done.error) == (JobStatus.failed, 3, "the job exited with status 3")
    killed = service.start(
        JobSpec("kernel/build", python("import os, signal; os.kill(os.getpid(), signal.SIGUSR1)"))
    )
    done = finished(service, killed.job_id)
    assert (done.status, done.exit_code) == (JobStatus.failed, -signal.SIGUSR1)
    with pytest.raises(JobNotSucceeded):
        service.result(failing.job_id)


def test_output_goes_to_the_log_not_to_the_service(service: JobService) -> None:
    handle = service.start(
        JobSpec("kernel/build", python("import sys; print('out'); print('err', file=sys.stderr)"))
    )
    done = finished(service, handle.job_id)
    assert sorted(Path(done.log_path).read_text().split()) == ["err", "out"]


def test_progress_is_recorded_while_running_and_dropped_after(service: JobService, project: Path) -> None:
    handle = service.start(JobSpec("kernel/build", python("import time; time.sleep(600)")))
    job_id = handle.job_id
    assert (handle.progress.fraction, handle.progress.message) == (None, None)
    service.report_progress(job_id, fraction=0.25, message="building")
    expected = {"fraction": 0.5, "message": "building"}
    assert service.report_progress(job_id, fraction=0.5).progress.model_dump() == expected
    assert service.status(job_id).progress.model_dump() == expected
    with pytest.raises(ValueError):
        service.report_progress(job_id, fraction=1.5)
    with pytest.raises(ValueError):
        service.report_progress(job_id, message="x" * 501)
    service.cancel(job_id)
    assert service.report_progress(job_id, fraction=0.9).progress.fraction == 0.5
    with pytest.raises(UnknownJob):
        service.report_progress("nonexistent", fraction=0.1)


def test_cancel_kills_a_family_that_ignores_sigterm(service: JobService, project: Path, pids: Pids) -> None:
    marker = project / "pids"
    handle = service.start(JobSpec("collision/sweep", python(FAMILY, str(marker))))
    child, grandchild = pids.family(marker)
    cancelled = service.cancel(handle.job_id)
    assert (cancelled.status, cancelled.exit_code) == (JobStatus.cancelled, -signal.SIGKILL)
    pids.assert_gone(child, grandchild)
    assert service.cancel(handle.job_id) == cancelled  # idempotent
    assert service.status(handle.job_id).status == JobStatus.cancelled


def test_cancel_of_a_job_that_ended_keeps_its_status(service: JobService) -> None:
    handle = service.start(JobSpec("kernel/build", python("pass")))
    done = finished(service, handle.job_id)
    assert service.cancel(handle.job_id) == done
    assert done.status == JobStatus.succeeded


def test_a_process_left_behind_by_a_finished_job_is_killed(
    service: JobService, project: Path, pids: Pids
) -> None:
    marker = project / "grandchild"
    handle = service.start(JobSpec("kernel/build", python(LEAVER, str(marker))))
    assert finished(service, handle.job_id).status == JobStatus.succeeded
    grandchild = int(marker.read_text())
    pids.known.append(grandchild)
    pids.assert_gone(grandchild)


def test_a_group_that_outlives_its_command_is_killed_on_cancel(
    service: JobService, project: Path, pids: Pids
) -> None:
    marker = project / "pids"
    handle = service.start(JobSpec("kernel/build", python(LINGERER, str(marker))))
    child, grandchild = pids.family(marker)
    service.cancel(handle.job_id)
    pids.assert_gone(child, grandchild)


def test_reap_finishes_ended_jobs_without_being_asked_about_them(service: JobService) -> None:
    handle = service.start(JobSpec("kernel/build", python("pass")))
    reaped: list[JobHandle] = []
    assert wait_until(lambda: reaped.extend(service.reap()) or reaped, STARTUP_SECONDS)
    assert [(h.job_id, h.status) for h in reaped] == [(handle.job_id, JobStatus.succeeded)]


def test_closing_the_service_cancels_running_jobs(project: Path, pids: Pids) -> None:
    marker = project / "pids"
    with JobService(project, grace_seconds=0.2) as service:
        handle = service.start(JobSpec("kernel/build", python(FAMILY, str(marker))))
        child, grandchild = pids.family(marker)
    pids.assert_gone(child, grandchild)
    assert JobService(project).status(handle.job_id).status == JobStatus.cancelled


def test_closing_stops_every_job_even_when_one_record_is_lost(project: Path, pids: Pids) -> None:
    service = JobService(project, grace_seconds=0.2)
    markers = [project / "first", project / "second"]
    handles = [service.start(JobSpec("kernel/build", python(FAMILY, str(m)))) for m in markers]
    family = [pids.family(marker) for marker in markers]
    record = project / ".benchhand" / "runs" / f"{handles[0].job_id}.json"
    saved = record.read_text()
    record.unlink()
    with pytest.raises(ExceptionGroup) as raised:
        service.close()
    assert [type(error) for error in raised.value.exceptions] == [UnknownJob]
    pids.assert_gone(*family[0], *family[1])  # the lost record spared neither job
    record.write_text(saved)
    service.close()  # the kept outcome is written now
    assert [service.status(h.job_id).status for h in handles] == [JobStatus.cancelled] * 2


def test_list_jobs_and_unknown_ids(service: JobService) -> None:
    first = service.start(JobSpec("kernel/build", python("pass")))
    second = service.start(JobSpec("kernel/build", python("pass")))
    assert {h.job_id for h in service.list_jobs()} == {first.job_id, second.job_id}
    with pytest.raises(UnknownJob):
        service.status("nonexistent")


def test_concurrent_starts_get_distinct_records(service: JobService, project: Path) -> None:
    handles: list[JobHandle] = []

    def start() -> None:
        handles.append(service.start(JobSpec("kernel/build", python("pass"))))

    threads = [threading.Thread(target=start) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len({h.job_id for h in handles}) == 6
    assert len(list((project / ".benchhand" / "runs").glob("*.json"))) == 6


def test_a_program_that_cannot_start_leaves_no_record(service: JobService, project: Path) -> None:
    with pytest.raises(FileNotFoundError):
        service.start(JobSpec("kernel/build", ["benchhand-no-such-program"]))
    assert list((project / ".benchhand" / "runs").glob("*.json")) == []
    assert list((project / ".benchhand" / "runs").glob("*.log")) == []


def test_a_job_needs_a_valid_kind_and_a_command(service: JobService, project: Path) -> None:
    with pytest.raises(ValueError, match="kind"):
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
        other.cancel(handle.job_id)
    assert other.recovery.removed == ()


def test_progress_after_the_command_exited_is_dropped_even_if_nobody_reaped_it(
    service: JobService, project: Path
) -> None:
    handle = service.start(JobSpec("kernel/build", python("pass")))
    supervisor = json.loads((project / ".benchhand" / "runs" / f"{handle.job_id}.json").read_text())
    assert wait_until(lambda: not running(supervisor["process"]["pid"]), STARTUP_SECONDS)
    after = service.report_progress(handle.job_id, fraction=0.9)
    assert (after.status, after.progress.fraction) == (JobStatus.succeeded, None)


def test_a_failed_final_write_is_retried_with_the_same_outcome(
    service: JobService, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = service.start(JobSpec("kernel/build", python("import time; time.sleep(600)")))
    write = service._store.write
    broken = [True]

    def flaky(record: JobRecord) -> None:
        if broken[0] and record.status is JobStatus.cancelled:
            raise OSError("disk full")
        write(record)

    monkeypatch.setattr(service._store, "write", flaky)
    with pytest.raises(OSError, match="disk full"):
        service.cancel(handle.job_id)
    with pytest.raises(OSError, match="disk full"):
        service.status(handle.job_id)  # the outcome is kept, and written again on every ask
    broken[0] = False
    assert service.status(handle.job_id).status == JobStatus.cancelled  # not failed by the signal


def test_a_directory_is_no_result(service: JobService, project: Path) -> None:
    target = project / "out"
    target.mkdir()
    handle = service.start(JobSpec("kernel/build", python("pass"), result_path=target))
    assert finished(service, handle.job_id).result_path is None
    with pytest.raises(JobNotSucceeded):
        service.result(handle.job_id)


def test_a_job_id_that_is_a_path_names_no_job(service: JobService, project: Path) -> None:
    (project / ".benchhand" / "secret.json").write_text("{}")
    with pytest.raises(UnknownJob):
        service.status("../secret")
    with pytest.raises(UnknownJob):
        service.cancel("../secret")
