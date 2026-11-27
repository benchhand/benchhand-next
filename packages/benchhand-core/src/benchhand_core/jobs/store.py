# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The run records of one project: <project>/.benchhand/runs/<jobId>.json.

Each record is a JobRecord of contracts/jobs/job.schema.json: every read validates the file's JSON
against the contract, then parses it into the generated model. Files are replaced atomically.
`locked` serialises record creation and cleanup across processes. A job id becomes part of a path
only after it matches the contract's JobId, and a record belongs to the file that holds it only if
its jobId is the file's name.
"""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from benchhand_contracts import ContractViolation, validate
from benchhand_contracts.models.jobs.job_schema import JobRecord

from benchhand_core.jobs.errors import RecordError, UnknownJob

JOB_CONTRACT = "https://benchhand.github.io/benchhand/contracts/jobs/job.schema.json"


def _checked(job_id: str) -> str:
    try:
        validate(f"{JOB_CONTRACT}#/$defs/JobId", job_id)
    except ContractViolation:
        raise UnknownJob(f"no job {job_id!r}") from None
    return job_id


class RecordStore:
    def __init__(self, project_root: Path) -> None:
        self.runs_dir = Path(project_root).resolve() / ".benchhand" / "runs"

    def ensure(self) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        ignore = self.runs_dir / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n", encoding="utf-8")

    def record_path(self, job_id: str) -> Path:
        return self.runs_dir / f"{_checked(job_id)}.json"

    def log_path(self, job_id: str) -> Path:
        return self.runs_dir / f"{_checked(job_id)}.log"

    def default_result_path(self, job_id: str) -> Path:
        return self.runs_dir / f"{_checked(job_id)}.result"

    def paths(self) -> list[Path]:
        return sorted(self.runs_dir.glob("*.json"))

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.ensure()
        with open(self.runs_dir / ".lock", "a", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def write(self, record: JobRecord) -> None:
        path = self.record_path(record.job_id)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(record.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def read_path(self, path: Path) -> JobRecord:
        """Raises RecordError for a file that is no JobRecord or holds another job's id, and
        FileNotFoundError for a file that is gone."""
        try:
            contents = json.loads(path.read_text(encoding="utf-8"))
            validate(f"{JOB_CONTRACT}#/$defs/JobRecord", contents)
            record = JobRecord.model_validate(contents)
        except FileNotFoundError:
            raise
        except (OSError, ValueError) as error:  # ContractViolation and pydantic's error are ValueErrors
            raise RecordError(f"unreadable run record {path} ({type(error).__name__}: {error})") from error
        if record.job_id != path.stem:
            raise RecordError(f"run record {path} holds job {record.job_id!r}, not {path.stem!r}")
        return record

    def read(self, job_id: str) -> JobRecord:
        try:
            return self.read_path(self.record_path(job_id))
        except FileNotFoundError:
            raise UnknownJob(f"no job {job_id!r}") from None

    def delete(self, job_id: str, *, with_log: bool = False) -> None:
        self.record_path(job_id).unlink(missing_ok=True)
        if with_log:
            self.log_path(job_id).unlink(missing_ok=True)
