"""Aggregate-only owner for the legacy learning concept decay inspections."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Final

from .paths import DocumentsPlanePathError, documents_content_root, resolve_documents_read_path

SCHEMA: Final = "runtime.documents-learning-decay.v1"
MODES: Final = frozenset({"scan", "ls-orphan"})
_EXCLUDED_NAMES: Final = frozenset({"README.md", "INDEX.md", "_index.md"})
_STALENESS_BUCKETS: Final = ("fresh", "normal", "aging", "stale", "decayed", "uncommitted")


def _empty_counts() -> dict[str, int]:
    return {bucket: 0 for bucket in _STALENESS_BUCKETS}


def _unavailable(mode: str, error: str) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "status": "unavailable",
        "mode": mode,
        "checked_on": date.today().isoformat(),
        "concept_file_count": 0,
        "referenced_concept_count": 0,
        "orphan_concept_count": 0,
        "decay_candidate_count": 0,
        "staleness_counts": _empty_counts(),
        "error": error,
    }


def _concept_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in root.rglob("*.md")
            if path.is_file()
            and not path.is_symlink()
            and path.name not in _EXCLUDED_NAMES
            and not path.name.startswith("_ontology")
        )
    )


def _git_last_modified(vault_root: Path, relative_path: Path) -> date | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(vault_root), "log", "-1", "--format=%ai", "--", str(relative_path)],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    if not value:
        return None
    try:
        return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S").date()
    except ValueError:
        return None


def _last_modified(vault_root: Path, path: Path) -> date | None:
    try:
        relative = path.relative_to(vault_root)
    except ValueError:
        return None
    git_date = _git_last_modified(vault_root, relative)
    if git_date is not None:
        return git_date
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).date()
    except OSError:
        return None


def _bucket(age_days: int | None) -> str:
    if age_days is None:
        return "uncommitted"
    if age_days < 7:
        return "fresh"
    if age_days < 21:
        return "normal"
    if age_days < 30:
        return "aging"
    if age_days < 60:
        return "stale"
    return "decayed"


def inspect_learning_decay(
    documents_root: Path,
    *,
    domain_relative: str = "@学习进化/_knowledge/50-concepts",
    mode: str = "scan",
    today: date | None = None,
) -> dict[str, object]:
    """Inspect learning concepts without mutating Documents or returning names."""

    if mode not in MODES:
        raise DocumentsPlanePathError("learning inspection mode is unsupported")
    raw_documents = Path(documents_root).expanduser()
    if not raw_documents.is_dir() or raw_documents.is_symlink():
        raise DocumentsPlanePathError("Documents content root must be a regular directory")
    documents = raw_documents.resolve()
    root = resolve_documents_read_path(documents, domain_relative)
    if not root.is_dir() or root.is_symlink():
        raise DocumentsPlanePathError("learning concept root must be a regular directory")

    checked_on = today or date.today()
    paths = _concept_files(root)
    texts: dict[Path, str] = {}
    for path in paths:
        try:
            texts[path] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

    referenced = 0
    orphan = 0
    decay_candidates = 0
    staleness_counts = _empty_counts()
    for path in paths:
        filename = path.name
        reference_count = sum(1 for other, text in texts.items() if other != path and filename in text)
        if reference_count:
            referenced += 1
        else:
            orphan += 1
        modified = _last_modified(documents, path)
        age_days = (checked_on - modified).days if modified is not None else None
        if age_days is not None and age_days < 0:
            age_days = 0
        bucket = _bucket(age_days)
        staleness_counts[bucket] += 1
        if bucket in {"stale", "decayed"}:
            decay_candidates += 1

    status = "attention" if orphan or decay_candidates else "ok"
    return {
        "schema": SCHEMA,
        "status": status,
        "mode": mode,
        "checked_on": checked_on.isoformat(),
        "concept_file_count": len(paths),
        "referenced_concept_count": referenced,
        "orphan_concept_count": orphan,
        "decay_candidate_count": decay_candidates,
        "staleness_counts": staleness_counts,
        "error": None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inspect", nargs="?", choices=("inspect",), default="inspect")
    parser.add_argument("--mode", choices=sorted(MODES), default="scan")
    parser.add_argument("--domain-relative", default="@学习进化/_knowledge/50-concepts")
    parser.add_argument("--today")
    parser.add_argument("--documents-root", type=Path)
    args = parser.parse_args(argv)
    try:
        checked_on = date.fromisoformat(args.today) if args.today else date.today()
    except ValueError:
        payload = _unavailable(args.mode, "today_invalid")
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2

    root = args.documents_root or documents_content_root()
    try:
        payload = inspect_learning_decay(
            root,
            domain_relative=args.domain_relative,
            mode=args.mode,
            today=checked_on,
        )
    except DocumentsPlanePathError as exc:
        error = "documents_root_invalid" if "Documents" in str(exc) else "concept_root_invalid"
        payload = _unavailable(args.mode, error)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["status"] == "ok" else (1 if payload["status"] == "attention" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
