"""Explicit job registry and execution framework for Documents-plane owners."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from .commands import CommandResult, normalize_argv, run_owner_command
from .paths import (
    documents_content_root,
    ensure_runtime_state_root,
    resolve_documents_read_path,
    resolve_runtime_write_path,
    runtime_state_root,
)

_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class JobSpec:
    """Contract for an owner-owned command; Runtime does not define real jobs."""

    job_id: str
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    owner: str
    schedule: str
    timeout: float
    evidence_path: str
    fail_closed: bool


@dataclass(frozen=True)
class JobResult:
    """Execution outcome suitable for direct CLI serialization."""

    job_id: str
    owner: str
    dry_run: bool
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    evidence_path: Path | None

    @property
    def status(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.timed_out:
            return "timeout"
        return "succeeded" if self.exit_code == 0 else "failed"

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["evidence_path"] = (
            str(self.evidence_path) if self.evidence_path else None
        )
        result["status"] = self.status
        return result


class JobRegistry:
    """Injectable, in-memory registry. Owners must register their own commands."""

    def __init__(self) -> None:
        self._jobs: dict[str, tuple[JobSpec, tuple[str, ...]]] = {}

    def register(self, spec: JobSpec, owner_command: Sequence[str]) -> None:
        _validate_spec(spec)
        command = normalize_argv(owner_command)
        if spec.job_id in self._jobs:
            raise ValueError(f"duplicate Documents-plane job id: {spec.job_id}")
        self._jobs[spec.job_id] = (spec, command)

    def resolve(self, job_id: str) -> tuple[JobSpec, tuple[str, ...]]:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise ValueError(
                f"Documents-plane job is not registered: {job_id}"
            ) from exc


def _validate_spec(spec: JobSpec) -> None:
    if not _JOB_ID.fullmatch(spec.job_id):
        raise ValueError("job id must be a non-traversing identifier")
    if not isinstance(spec.owner, str) or not spec.owner.strip():
        raise ValueError("job owner must be non-empty")
    if not isinstance(spec.schedule, str) or not spec.schedule.strip():
        raise ValueError("job schedule must be non-empty")
    if not isinstance(spec.timeout, (int, float)) or spec.timeout <= 0:
        raise ValueError("job timeout must be positive")
    if not isinstance(spec.fail_closed, bool) or not spec.fail_closed:
        raise ValueError("Documents-plane jobs must be fail_closed")
    for paths in (spec.reads, spec.writes):
        if isinstance(paths, str):
            raise TypeError("job paths must be relative path sequences")
        for path in paths:
            _validate_declared_relative_path(path)
    _validate_declared_relative_path(spec.evidence_path)


def _validate_declared_relative_path(value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("job paths must be non-empty relative strings")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path == Path("."):
        raise ValueError("job paths must be relative and non-traversing")


def _validate_job_paths(
    spec: JobSpec, *, documents_root: Path, state_root: Path
) -> Path:
    for read_path in spec.reads:
        resolve_documents_read_path(documents_root, read_path)
    for write_path in spec.writes:
        resolve_runtime_write_path(
            state_root, write_path, documents_root=documents_root
        )
    return resolve_runtime_write_path(
        state_root, spec.evidence_path, documents_root=documents_root
    )


def _write_evidence(path: Path, result: JobResult) -> None:
    """Persist metadata only; owner stdout/stderr may contain Documents content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "job_id": result.job_id,
        "owner": result.owner,
        "status": result.status,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
    }
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def run_job(
    registry: JobRegistry,
    job_id: str,
    *,
    dry_run: bool = False,
    documents_root: str | Path | None = None,
    state_root: str | Path | None = None,
) -> JobResult:
    """Validate and invoke a registered owner command without reading Documents."""
    spec, command = registry.resolve(job_id)
    _validate_spec(spec)
    documents = (
        Path(documents_root).expanduser().resolve()
        if documents_root
        else documents_content_root()
    )
    state = (
        Path(state_root).expanduser().resolve() if state_root else runtime_state_root()
    )
    evidence_path = _validate_job_paths(
        spec, documents_root=documents, state_root=state
    )
    if dry_run:
        return JobResult(
            job_id=spec.job_id,
            owner=spec.owner,
            dry_run=True,
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            evidence_path=None,
        )

    ensured_state = ensure_runtime_state_root(state, documents_root=documents)
    evidence_path = _validate_job_paths(
        spec, documents_root=documents, state_root=ensured_state
    )
    command_result: CommandResult = run_owner_command(command, timeout=spec.timeout)
    result = JobResult(
        job_id=spec.job_id,
        owner=spec.owner,
        dry_run=False,
        exit_code=command_result.exit_code,
        stdout=command_result.stdout,
        stderr=command_result.stderr,
        timed_out=command_result.timed_out,
        evidence_path=evidence_path,
    )
    _write_evidence(evidence_path, result)
    return result
