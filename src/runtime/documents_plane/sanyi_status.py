"""Read-only consistency check for the Weijian 三医 status dashboard."""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from .paths import (
    DocumentsPlanePathError,
    documents_content_root,
    resolve_documents_read_path,
)

_SCHEMA = "runtime.documents-sanyi-status-consistency.v1"
_DOMAIN_RELATIVE = "@工作文档/卫健委"
_SCOPE_ENTITY_IDS = frozenset({"proj-syld", "proj-jingbao", "proj-emr-quality"})
_EXIT_CODES = {"ok": 0, "attention": 1, "unavailable": 2}
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LAST_REVIEWED = re.compile(
    r"^last-reviewed:\s*(?:'(?P<single>\d{4}-\d{2}-\d{2})'|\"(?P<double>\d{4}-\d{2}-\d{2})\"|(?P<bare>\d{4}-\d{2}-\d{2}))\s*$"
)


class _InspectionError(ValueError):
    """An input failure represented by a safe, stable error category."""


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


def _read_regular_file(path: Path, *, unavailable: str) -> str:
    try:
        file_stat = path.lstat()
    except OSError as exc:
        raise _InspectionError(unavailable) from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise _InspectionError(unavailable)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise _InspectionError(unavailable) from exc


def _dashboard_last_reviewed(path: Path) -> date:
    content = _read_regular_file(path, unavailable="dashboard_unavailable")
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        raise _InspectionError("dashboard_invalid")
    try:
        closing_index = lines.index("---", 1)
    except ValueError as exc:
        raise _InspectionError("dashboard_invalid") from exc
    candidates = [
        match
        for line in lines[1:closing_index]
        if (match := _LAST_REVIEWED.fullmatch(line)) is not None
    ]
    declared = [
        line for line in lines[1:closing_index] if line.startswith("last-reviewed:")
    ]
    if len(candidates) != 1 or len(declared) != 1:
        raise _InspectionError("dashboard_invalid")
    value = next(value for value in candidates[0].groups() if value is not None)
    parsed = _strict_iso_date(value)
    if parsed is None:
        raise _InspectionError("dashboard_invalid")
    return parsed


def _relevant_verified_dates(path: Path) -> tuple[date, ...]:
    content = _read_regular_file(path, unavailable="facts_unavailable")
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
        if not isinstance(entity_ids, list) or any(
            not isinstance(entity_id, str) for entity_id in entity_ids
        ):
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


def inspect_sanyi_status(
    domain_root: Path, *, today: date | None = None
) -> SanyiStatusConsistency:
    """Compare declared CR08 facts with dashboard frontmatter only."""
    checked_on = today or datetime.now(UTC).date()
    try:
        dashboard_date = _dashboard_last_reviewed(
            domain_root / "_control" / "三医态势仪表盘.md"
        )
        verified_dates = _relevant_verified_dates(
            domain_root / "_entities" / "facts" / "01-progress.yaml"
        )
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
    parser = argparse.ArgumentParser(prog="runtime-documents-sanyi-status")
    subcommands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subcommands.add_parser("inspect")
    inspect_parser.add_argument("--domain-relative", required=True)
    args = parser.parse_args(argv)
    checked_on = datetime.now(UTC).date()
    result = _unavailable(checked_on, "domain_invalid")
    if args.command == "inspect" and args.domain_relative == _DOMAIN_RELATIVE:
        try:
            domain = resolve_documents_read_path(
                documents_content_root(), _DOMAIN_RELATIVE
            )
        except DocumentsPlanePathError:
            pass
        else:
            result = inspect_sanyi_status(domain, today=checked_on)
    print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    return _EXIT_CODES[result.status]


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
