"""Cleanup of run records when a service starts, ported from the prototype's run record tests.

Records of live, orphaned, reused, foreign and broken entries; processes of dead owners.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from benchhand_contracts.models.jobs.job_schema import JobStatus
from benchhand_core.jobs import JobError, JobService, JobSpec
from benchhand_core.jobs.identity import process_identity
from conftest import Pids
from job_support import FAMILY, example_record, python, running, wait_until


def write_record(project: Path, pids: Pids, job_id: str = "stale0000001", **overrides: object) -> Path:
    """A record of a job whose owner and process ended, unless `overrides` say otherwise."""
    ended = pids.ended_pid()
    leader = {"pid": ended, "identity": "ended"}
    fields = {
        "jobId": job_id,
        "host": socket.gethostname(),
        "owner": leader,
        "process": leader,
        "logPath": str(project / ".benchhand" / "runs" / f"{job_id}.log"),
        **overrides,
    }
    record = example_record(**fields)
    path = project / ".benchhand" / "runs" / f"{job_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_the_record_of_an_ended_job_with_nothing_left_is_removed(project: Path, pids: Pids) -> None:
    path = write_record(project, pids)
    log = path.with_suffix(".log")
    log.write_text("old output")
    recovery = JobService(project).recovery
    assert recovery.removed == ("stale0000001",)
    assert not path.exists()
    assert not log.exists()


def test_a_record_whose_ids_were_reused_is_stale_and_never_signalled(project: Path, pids: Pids) -> None:
    other = pids.sleeper()
    reused = {"pid": other.pid, "identity": "an earlier process"}
    path = write_record(project, pids, owner=reused, process=reused)
    recovery = JobService(project).recovery
    assert recovery.removed == ("stale0000001",)
    assert not path.exists()
    assert other.poll() is None


def test_an_orphaned_job_is_reported_and_never_signalled(project: Path, pids: Pids) -> None:
    supervisor = pids.sleeper()
    path = write_record(
        project, pids, process={"pid": supervisor.pid, "identity": process_identity(supervisor.pid)}
    )
    service = JobService(project, grace_seconds=0.3)
    assert service.recovery.orphaned == ("stale0000001",)
    assert path.exists()
    assert service.status("stale0000001").status == JobStatus.running
    with pytest.raises(JobError, match="lost its owner"):
        service.cancel("stale0000001")
    assert supervisor.poll() is None
    assert path.exists()


def test_a_supervisor_that_ended_but_was_not_reaped_does_not_keep_its_job_orphaned(
    project: Path, pids: Pids
) -> None:
    zombie = subprocess.Popen([sys.executable, "-c", "pass"])  # ended, and nobody reaps it
    try:
        assert wait_until(lambda: not running(zombie.pid), 30)
        identity = process_identity(zombie.pid)
        assert identity is not None  # a zombie keeps its identity ...
        path = write_record(project, pids, process={"pid": zombie.pid, "identity": identity})
        recovery = JobService(project).recovery
    finally:
        zombie.wait()
    assert recovery.removed == ("stale0000001",)  # ... but it no longer runs
    assert not path.exists()


def test_a_job_whose_processes_ended_after_startup_is_cancelled_without_signals(
    project: Path, pids: Pids
) -> None:
    service = JobService(project)
    write_record(project, pids)
    cancelled = service.cancel("stale0000001")
    assert (cancelled.status, cancelled.exit_code) == (JobStatus.cancelled, None)


def test_a_job_whose_owner_runs_is_left_alone(project: Path, pids: Pids) -> None:
    holder = pids.sleeper()
    owner = {"pid": holder.pid, "identity": process_identity(holder.pid)}
    path = write_record(project, pids, owner=owner)
    recovery = JobService(project).recovery
    assert (recovery.removed, recovery.orphaned) == ((), ())
    assert path.exists()
    with pytest.raises(JobError, match="owned by process"):
        JobService(project).cancel("stale0000001")


def test_records_that_cannot_be_judged_are_reported_and_left(project: Path, pids: Pids) -> None:
    runs = project / ".benchhand" / "runs"
    runs.mkdir(parents=True)
    (runs / "broken.json").write_text("{", encoding="utf-8")
    (runs / "invalid.json").write_text(json.dumps({"jobId": "invalid"}), encoding="utf-8")
    elsewhere = write_record(project, pids, "elsewhere0001", host="another-host")
    write_record(project, pids, "badtime00001", createdAt="yesterday")
    python_names = {key: value for key, value in example_record().items() if key != "jobId"}
    python_names["job_id"] = "pythonnames1"  # the field's name, not its wire name
    invalid = {
        "pythonnames1": python_names,
        "extrafield01": example_record(jobId="extrafield01", unexpected=True),
    }
    for name, record in invalid.items():
        (runs / f"{name}.json").write_text(json.dumps(record), encoding="utf-8")
    renamed = write_record(project, pids, "original0001")
    renamed.rename(renamed.with_name("renamed0001.json"))
    recovery = JobService(project).recovery
    assert sorted(item.path.name for item in recovery.unverifiable) == [
        "badtime00001.json",
        "broken.json",
        "elsewhere0001.json",
        "extrafield01.json",
        "invalid.json",
        "pythonnames1.json",
        "renamed0001.json",
    ]
    assert recovery.removed == ()
    assert elsewhere.exists()
    assert (renamed.parent / "renamed0001.json").exists()


def test_a_service_killed_outright_takes_its_jobs_with_it(project: Path, pids: Pids) -> None:
    marker = project / "pids"
    owner_code = textwrap.dedent(f"""
        import time
        from benchhand_core.jobs import JobService, JobSpec
        service = JobService({str(project)!r})
        command = [{sys.executable!r}, "-c", {FAMILY!r}, {str(marker)!r}]
        handle = service.start(JobSpec("kernel/build", command))
        print(handle.job_id, flush=True)
        time.sleep(600)
    """)
    owner = subprocess.Popen([sys.executable, "-c", owner_code], stdout=subprocess.PIPE, text=True)
    assert owner.stdout is not None
    try:
        job_id = owner.stdout.readline().strip()
        child, grandchild = pids.family(marker)
        record = json.loads((project / ".benchhand" / "runs" / f"{job_id}.json").read_text())
        supervisor = record["process"]["pid"]
        pids.known += [owner.pid, supervisor]
        owner.send_signal(signal.SIGKILL)  # nothing of the service can clean up
    finally:
        owner.wait()
        owner.stdout.close()
    pids.assert_gone(supervisor, child, grandchild)
    recovery = JobService(project).recovery
    assert recovery.removed == (job_id,)
    assert not (project / ".benchhand" / "runs" / f"{job_id}.json").exists()


def test_a_second_service_of_the_project_leaves_the_first_ones_jobs(project: Path) -> None:
    with JobService(project, grace_seconds=0.2) as first:
        handle = first.start(JobSpec("kernel/build", python("import time; time.sleep(600)")))
        second = JobService(project)
        assert second.recovery.removed == ()
        assert second.status(handle.job_id).status == JobStatus.running
        assert (
            os.getpid()
            == json.loads(next((project / ".benchhand" / "runs").glob("*.json")).read_text())["owner"]["pid"]
        )
