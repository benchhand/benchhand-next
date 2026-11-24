"""The run records of one project: <project>/.benchhand/runs/<jobId>.json.

Each record is a JobRecord of contracts/jobs/job.schema.json, validated on every read and write.
Files are replaced atomically. `locked` serialises record creation and cleanup across processes.
"""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from jsonschema import ValidationError

from benchhand_core.jobs.errors import RecordError, UnknownJob
from benchhand_core.jobs.schema import validate_record

Record = dict[str, Any]


class RecordStore:
    def __init__(self, project_root: Path) -> None:
        self.runs_dir = Path(project_root).resolve() / ".benchhand" / "runs"

    def ensure(self) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        ignore = self.runs_dir / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n", encoding="utf-8")

    def record_path(self, job_id: str) -> Path:
        return self.runs_dir / f"{job_id}.json"

    def log_path(self, job_id: str) -> Path:
        return self.runs_dir / f"{job_id}.log"

    def default_result_path(self, job_id: str) -> Path:
        return self.runs_dir / f"{job_id}.result"

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

    def write(self, record: Record) -> None:
        validate_record(record)
        path = self.record_path(record["jobId"])
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def read_path(self, path: Path) -> Record:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            validate_record(record)
        except FileNotFoundError:
            raise
        except (OSError, ValueError, ValidationError) as error:
            raise RecordError(f"unreadable run record {path} ({type(error).__name__}: {error})") from error
        return record

    def read(self, job_id: str) -> Record:
        try:
            return self.read_path(self.record_path(job_id))
        except FileNotFoundError:
            raise UnknownJob(f"no job {job_id!r}") from None

    def delete(self, job_id: str, *, with_log: bool = False) -> None:
        self.record_path(job_id).unlink(missing_ok=True)
        if with_log:
            self.log_path(job_id).unlink(missing_ok=True)
