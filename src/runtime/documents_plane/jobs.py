"""Explicit, private execution registry for Documents-plane owners."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
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
_RUNTIME_IO_FAILURE = 74
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_EVIDENCE_PROJECTIONS = frozenset({"metadata", "facts-audit-v1"})


@dataclass(frozen=True)
class JobSpec:
    job_id: str
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    owner: str
    schedule: str
    timeout: float
    evidence_path: str
    fail_closed: bool
    evidence_projection: str = "metadata"


@dataclass(frozen=True)
class JobResult:
    job_id: str
    owner: str
    dry_run: bool
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    evidence_path: Path | None
    evidence_error: str | None = None
    evidence_summary: dict[str, object] | None = None

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


@dataclass
class _PrivateLayout:
    output_root: Path
    work_parent: Path
    evidence_path: Path
    evidence_parent_fd: int
    evidence_name: str

    def close(self) -> None:
        os.close(self.evidence_parent_fd)


class JobRegistry:
    """Injectable registry; owners must register their own command argv."""

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
    if spec.evidence_projection not in _EVIDENCE_PROJECTIONS:
        raise ValueError("job evidence projection is not supported")
    if isinstance(spec.reads, str) or isinstance(spec.writes, str):
        raise TypeError("job paths must be relative path sequences")
    for path in spec.reads:
        # A complete content-plane audit is an explicitly declared read of the
        # Documents root.  It is never valid for writes or evidence paths.
        if path != ".":
            _validate_declared_relative_path(path)
    for path in spec.writes:
        _validate_declared_relative_path(path)
    _validate_declared_relative_path(spec.evidence_path)


def _validate_declared_relative_path(value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("job paths must be non-empty relative strings")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path == Path("."):
        raise ValueError("job paths must be relative and non-traversing")


def _owner_output_root(state_root: Path, spec: JobSpec) -> Path:
    return state_root / "owner-output" / spec.job_id


def _evidence_path(state_root: Path, spec: JobSpec) -> Path:
    return state_root / "control" / "evidence" / spec.job_id / spec.evidence_path


def _validate_job_paths(
    spec: JobSpec, *, documents_root: Path, state_root: Path
) -> None:
    for read_path in spec.reads:
        if read_path != ".":
            resolve_documents_read_path(documents_root, read_path)
    resolve_runtime_write_path(state_root, "control", documents_root=documents_root)
    for write_path in spec.writes:
        resolve_runtime_write_path(
            _owner_output_root(state_root, spec),
            write_path,
            documents_root=documents_root,
        )


def _open_child_directory(parent_fd: int, name: str) -> int:
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    return os.open(name, _DIR_FLAGS, dir_fd=parent_fd)


def _open_relative_parent(root_fd: int, relative: Path) -> tuple[int, str]:
    current_fd = os.dup(root_fd)
    try:
        for part in relative.parts[:-1]:
            child_fd = _open_child_directory(current_fd, part)
            os.close(current_fd)
            current_fd = child_fd
        return current_fd, relative.name
    except BaseException:
        os.close(current_fd)
        raise


def _prepare_private_layout(state_root: Path, spec: JobSpec) -> _PrivateLayout:
    """Create private control/output roots with descriptor-anchored traversal."""
    state_fd = os.open(state_root, _DIR_FLAGS)
    evidence_parent_fd: int | None = None
    job_evidence_fd: int | None = None
    try:
        try:
            control_fd = _open_child_directory(state_fd, "control")
            try:
                evidence_fd = _open_child_directory(control_fd, "evidence")
                try:
                    job_evidence_fd = _open_child_directory(evidence_fd, spec.job_id)
                finally:
                    os.close(evidence_fd)
                runs_fd = _open_child_directory(control_fd, "runs")
                os.close(runs_fd)
            finally:
                os.close(control_fd)
            evidence_parent_fd, evidence_name = _open_relative_parent(
                job_evidence_fd, Path(spec.evidence_path)
            )
            os.close(job_evidence_fd)
            job_evidence_fd = None

            owner_fd = _open_child_directory(state_fd, "owner-output")
            try:
                output_fd = _open_child_directory(owner_fd, spec.job_id)
            finally:
                os.close(owner_fd)
            try:
                for write_path in spec.writes:
                    parent_fd, _ = _open_relative_parent(output_fd, Path(write_path))
                    os.close(parent_fd)
            finally:
                os.close(output_fd)
        except BaseException:
            if job_evidence_fd is not None:
                os.close(job_evidence_fd)
            if evidence_parent_fd is not None:
                os.close(evidence_parent_fd)
            raise
    finally:
        os.close(state_fd)
    if evidence_parent_fd is None:  # pragma: no cover - defensive
        raise RuntimeError("evidence layout completed without a parent descriptor")
    return _PrivateLayout(
        output_root=_owner_output_root(state_root, spec),
        work_parent=state_root / "control" / "runs",
        evidence_path=_evidence_path(state_root, spec),
        evidence_parent_fd=evidence_parent_fd,
        evidence_name=evidence_name,
    )


def _facts_audit_evidence(stdout: str) -> dict[str, object]:
    """Keep the Facts contract observable without storing source facts in Runtime state."""

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("facts-audit evidence must be a JSON object") from exc
    if not isinstance(payload, dict):
        raise TypeError("facts-audit evidence must be a JSON object")

    status = payload.get("status")
    facts_total = payload.get("facts_total")
    by_type = payload.get("by_type")
    errors = payload.get("errors")
    warnings = payload.get("warnings")
    if (
        status not in {"ok", "invalid"}
        or not isinstance(facts_total, int)
        or isinstance(facts_total, bool)
        or facts_total < 0
        or not isinstance(by_type, dict)
        or not isinstance(errors, list)
        or not isinstance(warnings, list)
    ):
        raise ValueError("facts-audit evidence has an invalid schema")

    normalized_types: dict[str, int] = {}
    for fact_type, count in by_type.items():
        if (
            not isinstance(fact_type, str)
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 0
        ):
            raise ValueError("facts-audit evidence has an invalid schema")
        normalized_types[fact_type] = count
    if sum(normalized_types.values()) != facts_total:
        raise ValueError("facts-audit evidence has an invalid schema")
    return {
        "schema": "runtime.documents-facts-audit.evidence.v1",
        "status": status,
        "facts_total": facts_total,
        "by_type": dict(sorted(normalized_types.items())),
        "error_count": len(errors),
        "warning_count": len(warnings),
    }


def _project_owner_evidence(spec: JobSpec, stdout: str) -> dict[str, object] | None:
    if spec.evidence_projection == "metadata":
        return None
    if spec.evidence_projection == "facts-audit-v1":
        return _facts_audit_evidence(stdout)
    raise ValueError(
        "job evidence projection is not supported"
    )  # pragma: no cover - validated at registration


def _persist_evidence(layout: _PrivateLayout, result: JobResult) -> None:
    """Atomically publish a receipt through an anchored no-follow directory FD."""
    payload = {
        "job_id": result.job_id,
        "owner": result.owner,
        "status": result.status,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "evidence_error": result.evidence_error,
    }
    if result.evidence_summary is not None:
        payload["owner_evidence"] = result.evidence_summary
    try:
        existing = os.stat(
            layout.evidence_name,
            dir_fd=layout.evidence_parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        existing = None
    if existing is not None and not stat.S_ISREG(existing.st_mode):
        raise OSError("evidence target is not a regular file")
    temporary_name = f".receipt-{secrets.token_hex(16)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary_name, flags, 0o600, dir_fd=layout.evidence_parent_fd)
    try:
        try:
            encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
            total = 0
            while total < len(encoded):
                written = os.write(fd, encoded[total:])
                if written <= 0:
                    raise OSError("evidence write made no progress")
                total += written
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(
            temporary_name,
            layout.evidence_name,
            src_dir_fd=layout.evidence_parent_fd,
            dst_dir_fd=layout.evidence_parent_fd,
        )
        os.fsync(layout.evidence_parent_fd)
    except BaseException:
        try:
            os.unlink(temporary_name, dir_fd=layout.evidence_parent_fd)
        except OSError:
            pass
        raise


def _failure_result(
    spec: JobSpec, error: OSError, *, owner_result: JobResult | None = None
) -> JobResult:
    message = str(error)
    if owner_result is not None and owner_result.exit_code != 0:
        return replace(owner_result, evidence_error=message)
    if owner_result is not None:
        return replace(
            owner_result, exit_code=_RUNTIME_IO_FAILURE, evidence_error=message
        )
    return JobResult(
        spec.job_id,
        spec.owner,
        False,
        _RUNTIME_IO_FAILURE,
        "",
        message + "\n",
        False,
        None,
        message,
    )


def run_job(
    registry: JobRegistry,
    job_id: str,
    *,
    dry_run: bool = False,
    documents_root: str | Path | None = None,
    state_root: str | Path | None = None,
) -> JobResult:
    """Validate and invoke a registered owner without exposing Runtime control paths."""
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
    _validate_job_paths(spec, documents_root=documents, state_root=state)
    if dry_run:
        return JobResult(spec.job_id, spec.owner, True, 0, "", "", False, None)
    try:
        ensured_state = ensure_runtime_state_root(state, documents_root=documents)
        _validate_job_paths(spec, documents_root=documents, state_root=ensured_state)
        layout = _prepare_private_layout(ensured_state, spec)
    except OSError as exc:
        return _failure_result(spec, exc)

    result: JobResult | None = None
    close_error: OSError | None = None
    try:
        allowed_paths = [layout.output_root / path for path in spec.writes]
        command_result: CommandResult = run_owner_command(
            command,
            timeout=spec.timeout,
            state_root=layout.output_root,
            documents_root=documents,
            allowed_write_roots=allowed_paths,
            work_root=layout.work_parent,
        )
        result = JobResult(
            spec.job_id,
            spec.owner,
            False,
            command_result.exit_code,
            command_result.stdout,
            command_result.stderr,
            command_result.timed_out,
            layout.evidence_path,
            command_result.setup_error,
        )
        if command_result.setup_error is None:
            try:
                evidence_summary = _project_owner_evidence(spec, command_result.stdout)
            except (TypeError, ValueError) as exc:
                result = replace(result, evidence_error=str(exc))
                if command_result.exit_code == 0:
                    result = _failure_result(
                        spec, OSError(str(exc)), owner_result=result
                    )
            else:
                result = replace(result, evidence_summary=evidence_summary)
        try:
            _persist_evidence(layout, result)
        except OSError as exc:
            result = _failure_result(spec, exc, owner_result=result)
    finally:
        try:
            layout.close()
        except OSError as exc:
            close_error = exc
    if close_error is not None:
        return _failure_result(spec, close_error, owner_result=result)
    if (
        result is None
    ):  # pragma: no cover - defensive; unexpected errors propagate above
        raise RuntimeError("owner execution completed without a result")
    return result
