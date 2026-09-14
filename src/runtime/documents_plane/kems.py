"""Read-only Documents KEMS change detection with Runtime-owned baselines."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .paths import (
    DocumentsPlanePathError,
    documents_content_root,
    resolve_documents_read_path,
    resolve_runtime_write_path,
    runtime_state_root,
)

_SCHEMA = "runtime.documents-kems-check.v1"
_SCOPES = ("inbox", "knowledge", "entities", "control", "buffer_inbox")


@dataclass(frozen=True)
class KemsCheck:
    """Bounded result of a legacy-compatible KEMS change scan."""

    status: str
    baseline: str
    changed_scopes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["changed_scopes"] = list(self.changed_scopes)
        payload["schema"] = _SCHEMA
        return dict(sorted(payload.items()))


def _inbox_path(domain_root: Path) -> Path:
    for name in ("01-Inbox", "inbox"):
        candidate = domain_root / "_storage" / name
        if candidate.is_dir():
            return candidate
    return domain_root / "_storage" / "01-Inbox"


def _fingerprint_directory(path: Path) -> str:
    """Fingerprint direct, non-hidden regular files without reading their content."""
    if not path.is_dir():
        return "not_found"
    try:
        digest = hashlib.sha256()
        for entry in sorted(path.iterdir(), key=lambda item: item.name):
            if entry.name.startswith("."):
                continue
            entry_stat = entry.lstat()
            if not stat.S_ISREG(entry_stat.st_mode):
                continue
            digest.update(os.fsencode(entry.name))
            digest.update(str(entry_stat.st_mtime_ns).encode("ascii"))
        return digest.hexdigest()
    except OSError:
        return "error"


def _load_baseline(state_path: Path) -> Mapping[str, str] | None:
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    hashes = payload.get("hashes") if isinstance(payload, dict) else None
    if not isinstance(hashes, dict) or not all(
        scope in _SCOPES and isinstance(value, str) for scope, value in hashes.items()
    ):
        return None
    return hashes


def _write_baseline(state_path: Path, hashes: Mapping[str, str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "schema": _SCHEMA,
                "checked_at": datetime.now(UTC).isoformat(),
                "hashes": dict(sorted(hashes.items())),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def check_kems(domain_root: Path, *, extra_inbox: Path | None, state_path: Path) -> KemsCheck:
    """Scan legacy KEMS scopes and persist only the baseline under Runtime state."""
    if not domain_root.is_dir():
        raise ValueError("domain root is missing")
    paths = {
        "inbox": _inbox_path(domain_root),
        "knowledge": domain_root / "_knowledge",
        "entities": domain_root / "_entities" / "entities",
        "control": domain_root / "_control",
    }
    if extra_inbox is not None and extra_inbox.is_dir():
        paths["buffer_inbox"] = extra_inbox
    hashes = {scope: _fingerprint_directory(path) for scope, path in paths.items()}
    previous = _load_baseline(state_path)
    changed = ()
    baseline = "initialized"
    if previous is not None:
        baseline = "existing"
        changed = tuple(
            scope
            for scope, fingerprint in hashes.items()
            if previous.get(scope) and previous[scope] != fingerprint and fingerprint != "not_found"
        )
    _write_baseline(state_path, hashes)
    return KemsCheck("changed" if changed else "ok", baseline, changed)


def main(argv: Sequence[str] | None = None) -> int:
    """Expose a sandboxable KEMS owner command with Runtime-only state output."""
    parser = argparse.ArgumentParser(prog="runtime-documents-kems")
    subcommands = parser.add_subparsers(dest="command", required=True)
    check_parser = subcommands.add_parser("check")
    check_parser.add_argument("--domain-relative", required=True)
    check_parser.add_argument("--extra-inbox-relative")
    check_parser.add_argument("--state-relative", required=True)
    args = parser.parse_args(argv)
    if args.command != "check":  # pragma: no cover - argparse owns this boundary
        return 2
    documents_root = documents_content_root()
    try:
        domain = resolve_documents_read_path(documents_root, args.domain_relative)
        extra_inbox = (
            resolve_documents_read_path(documents_root, args.extra_inbox_relative)
            if args.extra_inbox_relative
            else None
        )
        state_path = resolve_runtime_write_path(
            runtime_state_root(),
            args.state_relative,
            documents_root=documents_root,
        )
    except DocumentsPlanePathError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 2
    try:
        result = check_kems(domain, extra_inbox=extra_inbox, state_path=state_path)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
