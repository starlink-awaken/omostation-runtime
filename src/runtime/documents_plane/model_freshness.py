"""Bounded, read-only CR24 model freshness inspection."""

from __future__ import annotations

import argparse
import json
import re
import stat
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from .paths import (
    DocumentsPlanePathError,
    documents_content_root,
    resolve_documents_read_path,
)

_SCHEMA = "runtime.documents-model-freshness.v1"
_LAST_REVIEWED = re.compile(r"(?mi)^last-reviewed:\s*(\d{4}-\d{2}-\d{2})\s*$")
_LAST_REVIEWED_FIELD = re.compile(r"(?mi)^last-reviewed:\s*.*$")
_EXIT_CODES = {"ok": 0, "attention": 1, "unavailable": 2}


@dataclass(frozen=True)
class ModelFreshness:
    """Aggregate freshness result that excludes Documents file identity and text."""

    status: str
    checked_on: str
    facts_last_reviewed: str | None
    model_markdown_count: int
    fresh_model_count: int
    stale_model_count: int
    invalid_reviewed_count: int
    unreadable_regular_file_count: int
    error: str | None

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["schema"] = _SCHEMA
        return dict(sorted(payload.items()))


def _unavailable(
    checked_on: date,
    error: str,
    *,
    facts_last_reviewed: str | None = None,
    model_markdown_count: int = 0,
    invalid_reviewed_count: int = 0,
    unreadable_regular_file_count: int = 0,
) -> ModelFreshness:
    return ModelFreshness(
        status="unavailable",
        checked_on=checked_on.isoformat(),
        facts_last_reviewed=facts_last_reviewed,
        model_markdown_count=model_markdown_count,
        fresh_model_count=0,
        stale_model_count=0,
        invalid_reviewed_count=invalid_reviewed_count,
        unreadable_regular_file_count=unreadable_regular_file_count,
        error=error,
    )


def _reviewed_on(text: str) -> tuple[date | None, str | None]:
    matches = _LAST_REVIEWED.findall(text)
    fields = _LAST_REVIEWED_FIELD.findall(text)
    if not fields:
        return None, "missing"
    if len(fields) != 1 or len(matches) != 1:
        return None, "invalid"
    try:
        return date.fromisoformat(matches[0]), None
    except ValueError:
        return None, "invalid"


def _read_regular_file(
    path: Path, *, missing_error: str, not_regular_error: str, unreadable_error: str
) -> tuple[str | None, str | None]:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None, missing_error
    except OSError:
        return None, unreadable_error
    if not stat.S_ISREG(mode):
        return None, not_regular_error
    try:
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeError):
        return None, unreadable_error


def inspect_model_freshness(domain_root: Path, *, today: date | None = None) -> ModelFreshness:
    """Compare first-level model review dates with the facts review baseline."""
    checked_on = datetime.now(UTC).date() if today is None else today
    try:
        domain_mode = domain_root.lstat().st_mode
    except FileNotFoundError:
        return _unavailable(checked_on, "domain_root_missing")
    except OSError:
        return _unavailable(checked_on, "domain_root_unreadable")
    if not stat.S_ISDIR(domain_mode):
        return _unavailable(checked_on, "domain_root_not_direct")

    entities_dir = domain_root / "_entities"
    try:
        entities_mode = entities_dir.lstat().st_mode
    except FileNotFoundError:
        return _unavailable(checked_on, "entities_directory_missing")
    except OSError:
        return _unavailable(checked_on, "entities_directory_unreadable")
    if not stat.S_ISDIR(entities_mode):
        return _unavailable(checked_on, "entities_directory_not_direct")

    facts_text, facts_error = _read_regular_file(
        entities_dir / "facts.md",
        missing_error="facts_file_missing",
        not_regular_error="facts_file_not_regular",
        unreadable_error="facts_file_unreadable",
    )
    if facts_error is not None:
        return _unavailable(checked_on, facts_error)
    facts_reviewed, reviewed_error = _reviewed_on(facts_text or "")
    if reviewed_error is not None:
        return _unavailable(checked_on, f"facts_last_reviewed_{reviewed_error}")
    if facts_reviewed is None:  # pragma: no cover - guarded by reviewed_error
        return _unavailable(checked_on, "facts_last_reviewed_invalid")
    facts_reviewed_text = facts_reviewed.isoformat()

    models_dir = entities_dir / "models"
    try:
        models_mode = models_dir.lstat().st_mode
    except FileNotFoundError:
        return _unavailable(
            checked_on,
            "models_directory_missing",
            facts_last_reviewed=facts_reviewed_text,
        )
    except OSError:
        return _unavailable(
            checked_on,
            "models_directory_unreadable",
            facts_last_reviewed=facts_reviewed_text,
        )
    if not stat.S_ISDIR(models_mode):
        return _unavailable(
            checked_on,
            "models_directory_not_direct",
            facts_last_reviewed=facts_reviewed_text,
        )
    try:
        model_paths = sorted(
            (path for path in models_dir.iterdir() if path.suffix == ".md" and path.name != "README.md"),
            key=lambda path: path.name,
        )
    except OSError:
        return _unavailable(
            checked_on,
            "models_directory_unreadable",
            facts_last_reviewed=facts_reviewed_text,
        )
    model_count = len(model_paths)
    if model_count == 0:
        return _unavailable(
            checked_on,
            "models_directory_empty",
            facts_last_reviewed=facts_reviewed_text,
        )

    reviewed_dates: list[date] = []
    for path in model_paths:
        text, model_error = _read_regular_file(
            path,
            missing_error="model_file_unreadable",
            not_regular_error="model_file_not_regular",
            unreadable_error="model_file_unreadable",
        )
        if model_error is not None:
            return _unavailable(
                checked_on,
                model_error,
                facts_last_reviewed=facts_reviewed_text,
                model_markdown_count=model_count,
                unreadable_regular_file_count=int(model_error == "model_file_unreadable"),
            )
        reviewed, model_reviewed_error = _reviewed_on(text or "")
        if model_reviewed_error is not None:
            return _unavailable(
                checked_on,
                f"model_last_reviewed_{model_reviewed_error}",
                facts_last_reviewed=facts_reviewed_text,
                model_markdown_count=model_count,
                invalid_reviewed_count=1,
            )
        if reviewed is None:  # pragma: no cover - guarded by model_reviewed_error
            return _unavailable(
                checked_on,
                "model_last_reviewed_invalid",
                facts_last_reviewed=facts_reviewed_text,
                model_markdown_count=model_count,
                invalid_reviewed_count=1,
            )
        reviewed_dates.append(reviewed)

    stale_count = sum(reviewed < facts_reviewed for reviewed in reviewed_dates)
    fresh_count = model_count - stale_count
    return ModelFreshness(
        status="attention" if stale_count else "ok",
        checked_on=checked_on.isoformat(),
        facts_last_reviewed=facts_reviewed_text,
        model_markdown_count=model_count,
        fresh_model_count=fresh_count,
        stale_model_count=stale_count,
        invalid_reviewed_count=0,
        unreadable_regular_file_count=0,
        error=None,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Expose CR24 as a bounded Runtime owner command."""
    parser = argparse.ArgumentParser(prog="runtime-documents-model-freshness")
    subcommands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subcommands.add_parser("inspect")
    inspect_parser.add_argument("--domain-relative", required=True)
    args = parser.parse_args(argv)
    if args.command != "inspect":  # pragma: no cover - argparse owns this boundary
        return 2
    try:
        domain = resolve_documents_read_path(documents_content_root(), args.domain_relative)
        result = inspect_model_freshness(domain)
    except (DocumentsPlanePathError, OSError, ValueError):
        result = _unavailable(datetime.now(UTC).date(), "domain_path_invalid")
    print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    return _EXIT_CODES[result.status]


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
