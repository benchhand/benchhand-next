"""The job service: long jobs as private process groups, with run records, progress and cancellation.

A job is a command started under a supervisor (supervisor.py) that leads its own process group
and kills the whole group if the service process ends. Each job has a run record under
<project>/.benchhand/runs/ (store.py). Records and handles follow contracts/jobs/job.schema.json.

The service has no threads. `status`, `list_jobs`, `cancel` and `reap` notice jobs that ended,
kill what they left in their group, reap the supervisor and write the final status. The host
calls `reap` periodically so ended jobs do not wait for the next question about them.

Process identity rules (identity.py) make every check pid-reuse safe. On construction the service
cleans up: it removes the records of jobs whose processes are gone, leaves the records of jobs
whose owner still runs, and reports what it cannot judge without touching it.
"""

from __future__ import annotations

import os
import socket
import threading
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from benchhand_core.jobs.errors import JobError, JobNotSucceeded, RecordError
from benchhand_core.jobs.identity import (
    Unsupported,
    group_survives,
    process_identity,
    process_runs,
    require_posix,
)
from benchhand_core.jobs.process import DEFAULT_GRACE_SECONDS, SupervisedProcess, terminate_recorded_group
from benchhand_core.jobs.schema import validate_handle
from benchhand_core.jobs.store import Record, RecordStore

JobHandle = dict[str, Any]  # a JobHandle of contracts/jobs/job.schema.json
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
MAX_MESSAGE_LENGTH = 500  # JobProgress.message maxLength
JOB_ID_LENGTH = 12


@dataclass(frozen=True)
class JobSpec:
    """What to run. `env` is added to the service's environment. The job writes its result to
    `result_path`, which defaults to <runs>/<jobId>.result, and finds it in BENCHHAND_JOB_RESULT
    (its id is in BENCHHAND_JOB_ID)."""

    kind: str
    argv: Sequence[str]
    cwd: Path | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    result_path: Path | None = None


@dataclass(frozen=True)
class UnverifiableRecord:
    path: Path
    reason: str


@dataclass(frozen=True)
class Recovery:
    """What the cleanup at construction found. `removed`: ids of records whose processes are gone.
    `orphaned`: ids of jobs whose owner ended but whose processes still run; they are left alone
    and `cancel` stops them. `unverifiable`: records that cannot be judged."""

    removed: tuple[str, ...] = ()
    orphaned: tuple[str, ...] = ()
    unverifiable: tuple[UnverifiableRecord, ...] = ()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def handle_of(record: Record) -> JobHandle:
    """The handle of a run record. `resultPath` is set once the job succeeded and wrote it."""
    result = Path(record["resultPath"])
    handle = {
        "jobId": record["jobId"],
        "kind": record["kind"],
        "status": record["status"],
        "progress": dict(record["progress"]),
        "resultPath": str(result) if record["status"] == "succeeded" and result.exists() else None,
        "logPath": record["logPath"],
        "exitCode": record["exitCode"],
        "error": record["error"],
        "createdAt": record["createdAt"],
        "startedAt": record["startedAt"],
        "finishedAt": record["finishedAt"],
    }
    validate_handle(handle)
    return handle


def _describe_exit(code: int) -> str:
    return f"the job was killed by signal {-code}" if code < 0 else f"the job exited with status {code}"


class JobService:
    def __init__(self, project_root: Path, *, grace_seconds: float = DEFAULT_GRACE_SECONDS) -> None:
        require_posix()
        self.project_root = Path(project_root).resolve()
        self.grace_seconds = grace_seconds
        self._store = RecordStore(self.project_root)
        self._live: dict[str, SupervisedProcess] = {}
        self._lock = threading.RLock()
        self._owner = {"pid": os.getpid(), "identity": process_identity(os.getpid())}
        self.recovery = self._recover()

    # -- starting ------------------------------------------------------------------------------

    def start(self, spec: JobSpec) -> JobHandle:
        """Start a job in its own process group and record it. A missing or non-executable
        program raises FileNotFoundError or PermissionError, as subprocess does. An invalid kind
        raises jsonschema.ValidationError before anything is recorded."""
        if not spec.argv:
            raise ValueError("a job needs a command")
        cwd = Path(spec.cwd) if spec.cwd is not None else self.project_root
        with self._lock, self._store.locked():
            record = self._queue(spec, cwd)
            try:
                process = self._spawn(record, spec, cwd)
                self._mark_running(record, process)
            except BaseException:
                self._store.delete(record["jobId"], with_log=True)
                raise
            self._live[record["jobId"]] = process
            return handle_of(record)

    def _new_job_id(self) -> str:
        while True:
            job_id = uuid.uuid4().hex[:JOB_ID_LENGTH]
            if not self._store.record_path(job_id).exists():
                return job_id

    def _queue(self, spec: JobSpec, cwd: Path) -> Record:
        job_id = self._new_job_id()
        result = (
            Path(spec.result_path)
            if spec.result_path is not None
            else self._store.default_result_path(job_id)
        )
        record: Record = {
            "jobId": job_id,
            "kind": spec.kind,
            "status": "queued",
            "progress": {"fraction": None, "message": None},
            "argv": list(spec.argv),
            "cwd": str(cwd),
            "host": socket.gethostname(),
            "owner": dict(self._owner),
            "process": None,
            "resultPath": str(result.resolve()),
            "logPath": str(self._store.log_path(job_id)),
            "exitCode": None,
            "error": None,
            "createdAt": _now(),
            "startedAt": None,
            "finishedAt": None,
        }
        self._store.write(record)
        return record

    def _spawn(self, record: Record, spec: JobSpec, cwd: Path) -> SupervisedProcess:
        env = {
            **os.environ,
            **spec.env,
            "BENCHHAND_JOB_ID": record["jobId"],
            "BENCHHAND_JOB_RESULT": record["resultPath"],
        }
        with open(record["logPath"], "ab") as log:
            return SupervisedProcess(
                spec.argv, cwd=cwd, env=env, output=log, grace_seconds=self.grace_seconds
            )

    def _mark_running(self, record: Record, process: SupervisedProcess) -> None:
        record.update(
            status="running",
            process={"pid": process.pid, "identity": process.identity},
            startedAt=_now(),
        )
        try:
            self._store.write(record)
        except BaseException:
            process.terminate(grace_seconds=0)
            raise

    # -- asking --------------------------------------------------------------------------------

    def status(self, job_id: str) -> JobHandle:
        with self._lock:
            self._reap_job(job_id)
            return handle_of(self._store.read(job_id))

    def list_jobs(self) -> list[JobHandle]:
        """The handles of every readable record of this project."""
        with self._lock:
            self.reap()
            handles = []
            for path in self._store.paths():
                try:
                    handles.append(handle_of(self._store.read_path(path)))
                except (RecordError, FileNotFoundError):
                    continue
            return handles

    def result(self, job_id: str) -> Path:
        """The result file of a job that succeeded and wrote it."""
        handle = self.status(job_id)
        if handle["status"] != "succeeded":
            raise JobNotSucceeded(f"job {job_id} is {handle['status']}, not succeeded")
        if handle["resultPath"] is None:
            raise JobNotSucceeded(f"job {job_id} succeeded without writing its result")
        return Path(handle["resultPath"])

    def report_progress(
        self, job_id: str, *, fraction: float | None = None, message: str | None = None
    ) -> JobHandle:
        """Record the progress of a running job, as a provider `$/progress` notification
        reports it. Progress that arrives after the job ended is dropped."""
        if fraction is not None and not 0 <= fraction <= 1:
            raise ValueError(f"progress fraction {fraction} is outside 0..1")
        if message is not None and len(message) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"progress message is longer than {MAX_MESSAGE_LENGTH} characters")
        with self._lock:
            record = self._store.read(job_id)
            if record["status"] in TERMINAL:
                return handle_of(record)
            if job_id not in self._live:
                raise JobError(f"job {job_id} is not owned by this service")
            progress = record["progress"]
            record["progress"] = {
                "fraction": progress["fraction"] if fraction is None else fraction,
                "message": progress["message"] if message is None else message,
            }
            self._store.write(record)
            return handle_of(record)

    # -- ending --------------------------------------------------------------------------------

    def reap(self) -> list[JobHandle]:
        """Finish every job of this service whose process ended. Returns their handles."""
        with self._lock:
            return [handle for job_id in list(self._live) if (handle := self._reap_job(job_id)) is not None]

    def _reap_job(self, job_id: str) -> JobHandle | None:
        process = self._live.get(job_id)
        if process is None or not process.exited():
            return None
        return self._finish(job_id, process, cancelled=False)

    def _finish(self, job_id: str, process: SupervisedProcess, *, cancelled: bool) -> JobHandle:
        """Kill what the job left in its group, reap its supervisor and write the final status."""
        code = process.terminate(grace_seconds=0 if not cancelled else self.grace_seconds)
        del self._live[job_id]
        record = self._store.read(job_id)
        if cancelled:
            status, error = "cancelled", "the job was cancelled"
        elif code == 0:
            status, error = "succeeded", None
        else:
            status, error = "failed", _describe_exit(code)
        return self._write_final(record, status, code, error)

    def _write_final(self, record: Record, status: str, code: int | None, error: str | None) -> JobHandle:
        record.update(status=status, exitCode=code, error=error, finishedAt=_now())
        self._store.write(record)
        return handle_of(record)

    def cancel(self, job_id: str) -> JobHandle:
        """Stop a job: SIGTERM to its process group, the grace period, then SIGKILL. A job that
        already ended keeps its status. Raises JobError for a job another process owns."""
        with self._lock:
            record = self._store.read(job_id)
            if record["status"] in TERMINAL:
                return handle_of(record)
            process = self._live.get(job_id)
            if process is None:
                return self._cancel_unowned(record)
            return self._finish(job_id, process, cancelled=not process.exited())

    def _cancel_unowned(self, record: Record) -> JobHandle:
        state = self._judge(record)
        if state == "owned":
            raise JobError(
                f"job {record['jobId']} is owned by process {record['owner']['pid']}, which still runs"
            )
        if state == "unverifiable":
            raise JobError(f"job {record['jobId']} cannot be checked from this host")
        leader = record["process"]
        if leader is not None:
            terminate_recorded_group(leader["pid"], leader["identity"], self.grace_seconds)
        return self._write_final(record, "cancelled", None, "the job was cancelled")

    def close(self) -> None:
        """Cancel every running job of this service."""
        with self._lock:
            for job_id in list(self._live):
                self.cancel(job_id)

    def __enter__(self) -> JobService:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    # -- cleanup -------------------------------------------------------------------------------

    def _judge(self, record: Record) -> str:
        """`owned`: the owner still runs. `orphaned`: the owner is gone but processes run.
        `stale`: nothing runs. `unverifiable`: another host, or no way to check."""
        if record["host"] != socket.gethostname():
            return "unverifiable"
        process = record["process"]
        try:
            if process_runs(record["owner"]["pid"], record["owner"]["identity"]):
                return "owned"
            if process is not None and (
                process_runs(process["pid"], process["identity"])
                or group_survives(process["pid"], process["identity"])
            ):
                return "orphaned"
        except Unsupported:
            return "unverifiable"
        return "stale"

    def _recover(self) -> Recovery:
        removed: list[str] = []
        orphaned: list[str] = []
        unverifiable: list[UnverifiableRecord] = []
        with self._store.locked():
            for path in self._store.paths():
                try:
                    record = self._store.read_path(path)
                except RecordError as error:
                    unverifiable.append(UnverifiableRecord(path, str(error)))
                    continue
                except FileNotFoundError:
                    continue
                state = self._judge(record)
                if state == "stale":
                    self._store.delete(record["jobId"], with_log=True)
                    removed.append(record["jobId"])
                elif state == "orphaned":
                    orphaned.append(record["jobId"])
                elif state == "unverifiable":
                    unverifiable.append(UnverifiableRecord(path, f"a job recorded on host {record['host']}"))
        return Recovery(tuple(removed), tuple(orphaned), tuple(unverifiable))
