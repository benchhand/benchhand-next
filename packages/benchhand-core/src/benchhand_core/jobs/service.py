"""The job service: long jobs as private process groups, with run records, progress and cancellation.

A job is a command started under a supervisor (supervisor.py) that runs it in a process group of
its own and kills the whole group when the command ends or the service process does. Each job has a
run record under <project>/.benchhand/runs/ (store.py). Records and handles are the JobRecord and
JobHandle models generated from contracts/jobs/job.schema.json.

The service has no threads. `status`, `list_jobs`, `cancel`, `report_progress` and `reap` notice
jobs that ended, reap the supervisor and write the final status. The host calls `reap`
periodically so ended jobs do not wait for the next question about them.

This service signals only the supervisors it started and still holds unreaped; no process id read
from a record is ever signalled, since the id may have been reused. On construction the service
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

from benchhand_contracts.models.jobs.job_schema import (
    JobHandle,
    JobProgress,
    JobRecord,
    JobStatus,
    ProcessIdentity,
)

from benchhand_core.jobs.errors import JobError, JobNotSucceeded, RecordError
from benchhand_core.jobs.identity import Unsupported, process_identity, process_runs, require_posix
from benchhand_core.jobs.process import DEFAULT_GRACE_SECONDS, SupervisedProcess
from benchhand_core.jobs.store import RecordStore

TERMINAL = frozenset({JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled})
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
    `orphaned`: ids of jobs whose owner ended but whose supervisor still runs; it ends the job
    itself, and nothing here signals it. `unverifiable`: records that cannot be judged."""

    removed: tuple[str, ...] = ()
    orphaned: tuple[str, ...] = ()
    unverifiable: tuple[UnverifiableRecord, ...] = ()


@dataclass(frozen=True)
class _Outcome:
    """How a job ended, kept until its final record is written."""

    status: JobStatus
    exit_code: int | None
    error: str | None


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def handle_of(record: JobRecord) -> JobHandle:
    """The handle of a run record. `result_path` is set once the job succeeded and wrote its result."""
    result = Path(record.result_path)
    delivered = record.status is JobStatus.succeeded and result.is_file()
    return JobHandle(
        job_id=record.job_id,
        kind=record.kind,
        status=record.status,
        progress=record.progress.model_copy(),
        result_path=str(result) if delivered else None,
        log_path=record.log_path,
        exit_code=record.exit_code,
        error=record.error,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def _revised(record: JobRecord, **changes: Any) -> JobRecord:
    """A validated copy of `record` with `changes`."""
    return JobRecord.model_validate(record.model_dump() | changes)


def _describe_exit(code: int) -> str:
    return f"the job was killed by signal {-code}" if code < 0 else f"the job exited with status {code}"


class JobService:
    def __init__(self, project_root: Path, *, grace_seconds: float = DEFAULT_GRACE_SECONDS) -> None:
        require_posix()
        self.project_root = Path(project_root).resolve()
        self.grace_seconds = grace_seconds
        self._store = RecordStore(self.project_root)
        self._live: dict[str, SupervisedProcess] = {}
        self._pending: dict[str, _Outcome] = {}  # ended jobs whose final record is not yet written
        self._lock = threading.RLock()
        identity = process_identity(os.getpid())
        if identity is None:
            raise Unsupported("this process has no identity")
        self._owner = ProcessIdentity(pid=os.getpid(), identity=identity)
        self.recovery = self._recover()

    # -- starting ------------------------------------------------------------------------------

    def start(self, spec: JobSpec) -> JobHandle:
        """Start a job in its own process group and record it. A program that cannot be executed
        from the job's cwd raises FileNotFoundError or PermissionError, as subprocess does. An
        invalid kind raises pydantic's ValidationError (a ValueError). Nothing stays recorded
        after either."""
        if not spec.argv:
            raise ValueError("a job needs a command")
        cwd = Path(spec.cwd) if spec.cwd is not None else self.project_root
        with self._lock, self._store.locked():
            record = self._queue(spec, cwd)
            try:
                process = self._spawn(record, spec, cwd)
                record = self._mark_running(record, process)
            except BaseException:
                self._store.delete(record.job_id, with_log=True)
                raise
            self._live[record.job_id] = process
            return handle_of(record)

    def _new_job_id(self) -> str:
        while True:
            job_id = uuid.uuid4().hex[:JOB_ID_LENGTH]
            if not self._store.record_path(job_id).exists():
                return job_id

    def _queue(self, spec: JobSpec, cwd: Path) -> JobRecord:
        job_id = self._new_job_id()
        result = (
            Path(spec.result_path)
            if spec.result_path is not None
            else self._store.default_result_path(job_id)
        )
        record = JobRecord(
            job_id=job_id,
            kind=spec.kind,
            status=JobStatus.queued,
            progress=JobProgress(fraction=None, message=None),
            argv=list(spec.argv),
            cwd=str(cwd),
            host=socket.gethostname(),
            owner=self._owner,
            process=None,
            result_path=str(result.resolve()),
            log_path=str(self._store.log_path(job_id)),
            exit_code=None,
            error=None,
            created_at=_now(),
            started_at=None,
            finished_at=None,
        )
        self._store.write(record)
        return record

    def _spawn(self, record: JobRecord, spec: JobSpec, cwd: Path) -> SupervisedProcess:
        env = {
            **os.environ,
            **spec.env,
            "BENCHHAND_JOB_ID": record.job_id,
            "BENCHHAND_JOB_RESULT": record.result_path,
        }
        with open(record.log_path, "ab") as log:
            return SupervisedProcess(
                spec.argv, cwd=cwd, env=env, output=log, grace_seconds=self.grace_seconds
            )

    def _mark_running(self, record: JobRecord, process: SupervisedProcess) -> JobRecord:
        running = _revised(
            record,
            status=JobStatus.running,
            process=ProcessIdentity(pid=process.pid, identity=process.identity),
            started_at=_now(),
        )
        try:
            self._store.write(running)
        except BaseException:
            process.terminate()
            raise
        return running

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
        if handle.status is not JobStatus.succeeded:
            raise JobNotSucceeded(f"job {job_id} is {handle.status.value}, not succeeded")
        if handle.result_path is None:
            raise JobNotSucceeded(f"job {job_id} succeeded without writing its result")
        return Path(handle.result_path)

    def report_progress(
        self, job_id: str, *, fraction: float | None = None, message: str | None = None
    ) -> JobHandle:
        """Record the progress of a running job, as a provider `$/progress` notification
        reports it. Progress that arrives after the job ended is dropped. Raises ValueError for
        a fraction outside 0..1 or a message the contract's JobProgress does not allow."""
        JobProgress(fraction=fraction, message=message)
        with self._lock:
            self._reap_job(job_id)
            record = self._store.read(job_id)
            if record.status in TERMINAL:
                return handle_of(record)
            if job_id not in self._live:
                raise JobError(f"job {job_id} is not owned by this service")
            progress = JobProgress(
                fraction=record.progress.fraction if fraction is None else fraction,
                message=record.progress.message if message is None else message,
            )
            revised = _revised(record, progress=progress)
            self._store.write(revised)
            return handle_of(revised)

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
        """Stop the job if it still runs, reap its supervisor and write the final status. When the
        write fails, the job's outcome is kept and the next call writes it again."""
        outcome = self._pending.get(job_id)
        if outcome is None:
            outcome = self._pending[job_id] = _outcome_of(process.terminate(), cancelled=cancelled)
        handle = self._write_final(self._store.read(job_id), outcome)
        del self._live[job_id], self._pending[job_id]
        return handle

    def _write_final(self, record: JobRecord, outcome: _Outcome) -> JobHandle:
        final = _revised(
            record,
            status=outcome.status,
            exit_code=outcome.exit_code,
            error=outcome.error,
            finished_at=_now(),
        )
        self._store.write(final)
        return handle_of(final)

    def cancel(self, job_id: str) -> JobHandle:
        """Stop a job: SIGTERM to its process group, the grace period, then SIGKILL. A job that
        already ended keeps its status. Raises JobError for a job another process owns."""
        with self._lock:
            record = self._store.read(job_id)
            if record.status in TERMINAL:
                return handle_of(record)
            process = self._live.get(job_id)
            if process is None:
                return self._cancel_unowned(record)
            return self._finish(job_id, process, cancelled=not process.exited())

    def _cancel_unowned(self, record: JobRecord) -> JobHandle:
        state = self._judge(record)
        if state == "owned":
            raise JobError(f"job {record.job_id} is owned by process {record.owner.pid}, which still runs")
        if state == "orphaned":
            raise JobError(
                f"job {record.job_id} lost its owner and is not signalled from here: its supervisor ends it"
            )
        if state == "unverifiable":
            raise JobError(f"job {record.job_id} cannot be checked from this host")
        return self._write_final(record, _outcome_of(None, cancelled=True))

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

    def _judge(self, record: JobRecord) -> str:
        """`owned`: the owner still runs. `orphaned`: the owner is gone but the supervisor runs.
        `stale`: nothing runs. `unverifiable`: another host, or no way to check."""
        if record.host != socket.gethostname():
            return "unverifiable"
        try:
            if process_runs(record.owner.pid, record.owner.identity):
                return "owned"
            if record.process is not None and process_runs(record.process.pid, record.process.identity):
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
                    self._store.delete(record.job_id, with_log=True)
                    removed.append(record.job_id)
                elif state == "orphaned":
                    orphaned.append(record.job_id)
                elif state == "unverifiable":
                    unverifiable.append(UnverifiableRecord(path, f"a job recorded on host {record.host}"))
        return Recovery(tuple(removed), tuple(orphaned), tuple(unverifiable))


def _outcome_of(code: int | None, *, cancelled: bool) -> _Outcome:
    """`code` is None only for a job whose process is gone and whose status nobody saw."""
    if cancelled or code is None:
        return _Outcome(JobStatus.cancelled, code, "the job was cancelled")
    if code == 0:
        return _Outcome(JobStatus.succeeded, 0, None)
    return _Outcome(JobStatus.failed, code, _describe_exit(code))
