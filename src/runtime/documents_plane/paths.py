"""Fail-closed path boundaries for the Documents content plane."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path


class DocumentsPlanePathError(ValueError):
    """Raised when a Documents-plane path violates the ownership boundary."""


def documents_content_root(environ: Mapping[str, str] | None = None) -> Path:
    """Return the read-only Documents root without creating or writing it."""
    env = os.environ if environ is None else environ
    return (
        Path(env.get("DOCUMENTS_CONTENT_ROOT", str(Path.home() / "Documents")))
        .expanduser()
        .resolve()
    )


def runtime_state_root(environ: Mapping[str, str] | None = None) -> Path:
    """Return Runtime's only write root, using the XDG state default."""
    env = os.environ if environ is None else environ
    configured = env.get("OMOSTATION_RUNTIME_STATE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    xdg_state = Path(env.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
    return (xdg_state / "omostation" / "runtime").expanduser().resolve()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _relative_path(value: str | Path, *, label: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise DocumentsPlanePathError(
            f"{label} must be a relative, non-traversing path"
        )
    if path == Path("."):
        raise DocumentsPlanePathError(
            f"{label} must name a file or directory below its root"
        )
    return path


def resolve_documents_read_path(
    documents_root: str | Path, relative_path: str | Path
) -> Path:
    """Resolve a read target and reject traversal or symlink escapes."""
    root = Path(documents_root).expanduser().resolve()
    candidate = (
        root / _relative_path(relative_path, label="Documents read path")
    ).resolve()
    if not _is_within(candidate, root):
        raise DocumentsPlanePathError(
            "Documents read path escapes DOCUMENTS_CONTENT_ROOT"
        )
    return candidate


def resolve_runtime_write_path(
    state_root: str | Path,
    relative_path: str | Path,
    *,
    documents_root: str | Path,
) -> Path:
    """Resolve a Runtime write target while refusing Documents and all escapes."""
    state = Path(state_root).expanduser().resolve()
    documents = Path(documents_root).expanduser().resolve()
    if _is_within(state, documents):
        raise DocumentsPlanePathError(
            "OMOSTATION_RUNTIME_STATE_ROOT must not be inside DOCUMENTS_CONTENT_ROOT"
        )
    candidate = (
        state / _relative_path(relative_path, label="Runtime write path")
    ).resolve()
    if not _is_within(candidate, state) or _is_within(candidate, documents):
        raise DocumentsPlanePathError(
            "Runtime write path escapes OMOSTATION_RUNTIME_STATE_ROOT"
        )
    return candidate


def ensure_runtime_state_root(
    state_root: str | Path, *, documents_root: str | Path
) -> Path:
    """Create the approved Runtime write root after containment validation."""
    state = Path(state_root).expanduser().resolve()
    documents = Path(documents_root).expanduser().resolve()
    if _is_within(state, documents):
        raise DocumentsPlanePathError(
            "OMOSTATION_RUNTIME_STATE_ROOT must not be inside DOCUMENTS_CONTENT_ROOT"
        )
    state.mkdir(parents=True, exist_ok=True)
    resolved = state.resolve()
    if _is_within(resolved, documents):
        raise DocumentsPlanePathError(
            "OMOSTATION_RUNTIME_STATE_ROOT resolves inside DOCUMENTS_CONTENT_ROOT"
        )
    return resolved
