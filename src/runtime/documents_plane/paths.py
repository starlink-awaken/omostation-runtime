"""Fail-closed path boundaries for the Documents content plane."""

from __future__ import annotations

import os
import unicodedata
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


def _identity_parts(path: Path) -> tuple[str, ...]:
    """Conservative APFS-style identity spelling for not-yet-created paths."""
    return tuple(unicodedata.normalize("NFC", part).casefold() for part in path.parts)


def _identity_within(path: Path, root: Path) -> bool:
    path_parts = _identity_parts(path)
    root_parts = _identity_parts(root)
    return (
        len(path_parts) >= len(root_parts)
        and path_parts[: len(root_parts)] == root_parts
    )


def _nearest_existing_ancestor(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def require_disjoint_roots(
    state_root: str | Path, documents_root: str | Path
) -> tuple[Path, Path]:
    """Resolve and require strictly separate Runtime-state and Documents roots."""
    state = Path(state_root).expanduser().resolve()
    documents = Path(documents_root).expanduser().resolve()
    state_anchor = _nearest_existing_ancestor(state)
    documents_anchor = _nearest_existing_ancestor(documents)
    same_anchor = False
    if state_anchor == state or documents_anchor == documents:
        try:
            same_anchor = os.path.samefile(state_anchor, documents_anchor)
        except OSError:
            same_anchor = True
    if (
        _identity_within(state, documents)
        or _identity_within(documents, state)
        or same_anchor
    ):
        raise DocumentsPlanePathError(
            "OMOSTATION_RUNTIME_STATE_ROOT and DOCUMENTS_CONTENT_ROOT must not overlap"
        )
    return state, documents


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
    state, documents = require_disjoint_roots(state_root, documents_root)
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
    state, documents = require_disjoint_roots(state_root, documents_root)
    state.mkdir(parents=True, exist_ok=True)
    resolved, _ = require_disjoint_roots(state, documents)
    return resolved
