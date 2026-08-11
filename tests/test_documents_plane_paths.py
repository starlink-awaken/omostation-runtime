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
