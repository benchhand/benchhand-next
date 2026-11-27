# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The job service: long jobs as supervised process groups with run records, progress and cancellation."""

from benchhand_contracts.models.jobs.job_schema import JobHandle

from benchhand_core.jobs.errors import JobError, JobNotSucceeded, RecordError, UnknownJob
from benchhand_core.jobs.identity import Unsupported, process_identity
from benchhand_core.jobs.service import JobService, JobSpec, Recovery, UnverifiableRecord

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
