"""Governed execution adapters for the Documents content plane.

The package deliberately contains no Documents content or cross-layer business
logic. It only validates paths, invokes explicitly registered owner commands,
and records metadata-only execution evidence under Runtime state.
"""

from .jobs import JobRegistry, JobResult, JobSpec, run_job

__all__ = ["JobRegistry", "JobResult", "JobSpec", "run_job"]
