"""Read-only consistency check for the Weijian 三医 status dashboard."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

_SCHEMA = "runtime.documents-sanyi-status-consistency.v1"
_DOMAIN_RELATIVE = "@工作文档/卫健委"
_SCOPE_ENTITY_IDS = frozenset({"proj-syld", "proj-jingbao", "proj-emr-quality"})
_EXIT_CODES = {"ok": 0, "attention": 1, "unavailable": 2}
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LAST_REVIEWED = re.compile(
    r"^last-reviewed:\s*(?:'(?P<single>\d{4}-\d{2}-\d{2})'|\"(?P<double>\d{4}-\d{2}-\d{2})\"|(?P<bare>\d{4}-\d{2}-\d{2}))\s*$"
)
_MAX_INPUT_BYTES = 1024 * 1024


class _InspectionError(ValueError):
    """An input failure represented by a safe, stable error category."""


class _ArgumentParseError(ValueError):
    """A deliberately detail-free owner CLI parsing failure."""


class _RedactingArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise _ArgumentParseError


@dataclass(frozen=True)
class SanyiStatusConsistency:
    """Aggregate-only owner result that is safe to persist in Runtime state."""

    status: str
    checked_on: str
    dashboard_last_reviewed: str | None
    latest_verified_at: str | None
    relevant_fact_count: int
    error: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": _SCHEMA,
            "status": self.status,
            "checked_on": self.checked_on,
            "dashboard_last_reviewed": self.dashboard_last_reviewed,
            "latest_verified_at": self.latest_verified_at,
            "relevant_fact_count": self.relevant_fact_count,
            "error": self.error,
        }


def _strict_iso_date(value: object) -> date | None:
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _open_directory(path: Path, *, unavailable: str) -> int:
    try:
        before = path.lstat()
    except OSError as exc:
        raise _InspectionError(unavailable) from exc
    if not stat.S_ISDIR(before.st_mode):
        raise _InspectionError(unavailable)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise _InspectionError(unavailable)
    try:
        descriptor = os.open(path, os.O_RDONLY | directory | nofollow)
    except (OSError, UnicodeError) as exc:
        raise _InspectionError(unavailable) from exc

    try:
        opened = os.fstat(descriptor)
    except OSError as exc:
        os.close(descriptor)
        raise _InspectionError(unavailable) from exc
    if not stat.S_ISDIR(opened.st_mode) or (before.st_dev, before.st_ino) != (
        opened.st_dev,
        opened.st_ino,
    ):
        os.close(descriptor)
        raise _InspectionError(unavailable)
    return descriptor


def _read_documents_regular_file(documents_root: Path, relative_parts: tuple[str, ...], *, unavailable: str) -> str:
    """Read one fixed Documents input through no-follow directory descriptors."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise _InspectionError(unavailable)
    directory_descriptor = _open_directory(documents_root, unavailable=unavailable)
    file_descriptor: int | None = None
    try:
        for component in relative_parts[:-1]:
            try:
                before = os.stat(component, dir_fd=directory_descriptor, follow_symlinks=False)
                if not stat.S_ISDIR(before.st_mode):
                    raise _InspectionError(unavailable)
                next_descriptor = os.open(
                    component,
                    os.O_RDONLY | directory | nofollow,
                    dir_fd=directory_descriptor,
                )
            except (OSError, UnicodeError) as exc:
                raise _InspectionError(unavailable) from exc
            opened = os.fstat(next_descriptor)
            if not stat.S_ISDIR(opened.st_mode) or (before.st_dev, before.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            ):
                os.close(next_descriptor)
                raise _InspectionError(unavailable)
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor

        filename = relative_parts[-1]
        try:
            before = os.stat(filename, dir_fd=directory_descriptor, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode):
                raise _InspectionError(unavailable)
            file_descriptor = os.open(
                filename,
                os.O_RDONLY | nofollow,
                dir_fd=directory_descriptor,
            )
        except (OSError, UnicodeError) as exc:
            raise _InspectionError(unavailable) from exc
        opened = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or opened.st_size > _MAX_INPUT_BYTES
        ):
            raise _InspectionError(unavailable)
        chunks: list[bytes] = []
        remaining = _MAX_INPUT_BYTES + 1
        while remaining:
            chunk = os.read(file_descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining == 0:
            raise _InspectionError(unavailable)
        after = os.stat(filename, dir_fd=directory_descriptor, follow_symlinks=False)
        if not stat.S_ISREG(after.st_mode) or (opened.st_dev, opened.st_ino) != (
            after.st_dev,
            after.st_ino,
        ):
            raise _InspectionError(unavailable)
        return b"".join(chunks).decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise _InspectionError(unavailable) from exc
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        os.close(directory_descriptor)


def _dashboard_last_reviewed(documents_root: Path) -> date:
    content = _read_documents_regular_file(
        documents_root,
        ("@工作文档", "卫健委", "_control", "三医态势仪表盘.md"),
        unavailable="dashboard_unavailable",
    )
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        raise _InspectionError("dashboard_invalid")
    try:
        closing_index = lines.index("---", 1)
    except ValueError as exc:
        raise _InspectionError("dashboard_invalid") from exc
    candidates = [match for line in lines[1:closing_index] if (match := _LAST_REVIEWED.fullmatch(line)) is not None]
    declared = [line for line in lines[1:closing_index] if line.startswith("last-reviewed:")]
    if len(candidates) != 1 or len(declared) != 1:
        raise _InspectionError("dashboard_invalid")
    value = next(value for value in candidates[0].groups() if value is not None)
    parsed = _strict_iso_date(value)
    if parsed is None:
        raise _InspectionError("dashboard_invalid")
    return parsed


def _relevant_verified_dates(documents_root: Path) -> tuple[date, ...]:
    content = _read_documents_regular_file(
        documents_root,
        ("@工作文档", "卫健委", "_entities", "facts", "01-progress.yaml"),
        unavailable="facts_unavailable",
    )
    try:
        document: Any = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise _InspectionError("facts_invalid") from exc
    if not isinstance(document, dict) or not isinstance(document.get("facts"), list):
        raise _InspectionError("facts_invalid")

    verified_dates: list[date] = []
    for fact in document["facts"]:
        if not isinstance(fact, dict):
            raise _InspectionError("facts_invalid")
        entity_ids = fact.get("entity_ids")
        if not isinstance(entity_ids, list) or any(not isinstance(entity_id, str) for entity_id in entity_ids):
            raise _InspectionError("facts_invalid")
        if not _SCOPE_ENTITY_IDS.intersection(entity_ids):
            continue
        verified_at = _strict_iso_date(fact.get("verified_at"))
        if verified_at is None:
            raise _InspectionError("facts_invalid")
        verified_dates.append(verified_at)
    if not verified_dates:
        raise _InspectionError("facts_scope_empty")
    return tuple(verified_dates)


def _unavailable(checked_on: date, error: str) -> SanyiStatusConsistency:
    return SanyiStatusConsistency(
        status="unavailable",
        checked_on=checked_on.isoformat(),
        dashboard_last_reviewed=None,
        latest_verified_at=None,
        relevant_fact_count=0,
        error=error,
    )


def inspect_sanyi_status(documents_root: Path, *, today: date | None = None) -> SanyiStatusConsistency:
    """Compare declared CR08 facts with dashboard frontmatter only."""
    checked_on = today or datetime.now(UTC).date()
    try:
        dashboard_date = _dashboard_last_reviewed(documents_root)
        verified_dates = _relevant_verified_dates(documents_root)
    except _InspectionError as exc:
        return _unavailable(checked_on, str(exc))
    latest = max(verified_dates)
    return SanyiStatusConsistency(
        status="attention" if latest > dashboard_date else "ok",
        checked_on=checked_on.isoformat(),
        dashboard_last_reviewed=dashboard_date.isoformat(),
        latest_verified_at=latest.isoformat(),
        relevant_fact_count=len(verified_dates),
        error=None,
    )


def main(argv: list[str] | None = None) -> int:
    """Run the owner with its single declared Documents read root."""
    parser = _RedactingArgumentParser(prog="runtime-documents-sanyi-status")
    subcommands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subcommands.add_parser("inspect")
    inspect_parser.add_argument("--domain-relative", required=True)
    checked_on = datetime.now(UTC).date()
    try:
        args = parser.parse_args(argv)
    except _ArgumentParseError:
        result = _unavailable(checked_on, "arguments_invalid")
        print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
        return _EXIT_CODES[result.status]
    result = _unavailable(checked_on, "domain_invalid")
    if args.command == "inspect" and args.domain_relative == _DOMAIN_RELATIVE:
        try:
            configured_root = Path(
                os.environ.get("DOCUMENTS_CONTENT_ROOT", str(Path.home() / "Documents"))
            ).expanduser()
            result = inspect_sanyi_status(configured_root, today=checked_on)
        except (OSError, UnicodeError):
            pass
    print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    return _EXIT_CODES[result.status]


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
