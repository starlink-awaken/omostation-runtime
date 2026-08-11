from __future__ import annotations

from pathlib import Path

import pytest
from runtime.documents_plane.paths import (
    DocumentsPlanePathError,
    ensure_runtime_state_root,
    resolve_documents_read_path,
    resolve_runtime_write_path,
)


def test_documents_reads_reject_traversal_and_absolute_paths(tmp_path: Path) -> None:
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()

    with pytest.raises(DocumentsPlanePathError):
        resolve_documents_read_path(documents_root, "../secret.txt")
    with pytest.raises(DocumentsPlanePathError):
        resolve_documents_read_path(documents_root, tmp_path / "secret.txt")


def test_runtime_writes_refuse_documents_content_root(tmp_path: Path) -> None:
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()

    with pytest.raises(DocumentsPlanePathError):
        resolve_runtime_write_path(
            documents_root,
            "evidence/receipt.json",
            documents_root=documents_root,
        )


def test_runtime_state_root_is_created_outside_documents(tmp_path: Path) -> None:
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()
    state_root = tmp_path / "state" / "runtime"

    actual = ensure_runtime_state_root(state_root, documents_root=documents_root)

    assert actual == state_root.resolve()
    assert actual.is_dir()


@pytest.mark.parametrize(
    ("state_root", "documents_root"),
    [
        ("state", "state/Documents"),
        ("same-root", "same-root"),
    ],
)
def test_runtime_and_documents_roots_reject_any_overlap(
    tmp_path: Path, state_root: str, documents_root: str
) -> None:
    with pytest.raises(DocumentsPlanePathError, match="overlap"):
        resolve_runtime_write_path(
            tmp_path / state_root,
            "evidence/receipt.json",
            documents_root=tmp_path / documents_root,
        )
    with pytest.raises(DocumentsPlanePathError, match="overlap"):
        ensure_runtime_state_root(
            tmp_path / state_root, documents_root=tmp_path / documents_root
        )


def test_runtime_and_documents_sibling_roots_are_allowed(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    documents_root = tmp_path / "Documents"

    actual = ensure_runtime_state_root(state_root, documents_root=documents_root)

    assert actual == state_root.resolve()
    assert (
        resolve_runtime_write_path(
            state_root, "evidence/receipt.json", documents_root=documents_root
        )
        == state_root / "evidence/receipt.json"
    )
