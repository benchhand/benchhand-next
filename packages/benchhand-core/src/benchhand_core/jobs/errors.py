"""Errors of the job service."""

from __future__ import annotations


class JobError(RuntimeError):
    """A job cannot be started, found, or asked to do what was requested."""


class UnknownJob(JobError):
    """No record of that job id."""


class JobNotSucceeded(JobError):
    """A result was requested of a job that has not succeeded."""


class RecordError(JobError):
    """A run record is unreadable or does not match the job contract."""
