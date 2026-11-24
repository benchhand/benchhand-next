"""The job service: long jobs as supervised process groups with run records, progress and cancellation."""

from benchhand_core.jobs.errors import JobError, JobNotSucceeded, RecordError, UnknownJob
from benchhand_core.jobs.identity import Unsupported, process_identity
from benchhand_core.jobs.service import JobHandle, JobService, JobSpec, Recovery, UnverifiableRecord

__all__ = [
    "JobError",
    "JobHandle",
    "JobNotSucceeded",
    "JobService",
    "JobSpec",
    "RecordError",
    "Recovery",
    "UnknownJob",
    "Unsupported",
    "UnverifiableRecord",
    "process_identity",
]
