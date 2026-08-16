"""Bounded, read-only health projection for the Weijian control inputs."""

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

_SCHEMA = "runtime.documents-control-health.v1"
_SIGNAL_TYPE = re.compile(r"(?m)^\s*(?:-\s*)?type:\s*(🔴|⚠️|✅)\s*$")
_LAST_REVIEWED = re.compile(r"(?mi)^last-reviewed:\s*(\d{4}-\d{2}-\d{2})\s*$")


@dataclass(frozen=True)
class ControlHealth:
    """Small controller-input summary with no Documents content in its output."""

    status: str
    signal_counts: dict[str, int]
    facts_view_status: str
    reviewed_on: str | None
    facts_view_age_days: int | None

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["schema"] = _SCHEMA
        return dict(sorted(payload.items()))


def _regular_text(path: Path) -> str | None:
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode):
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _signal_counts(signals: str) -> dict[str, int]:
    symbols = _SIGNAL_TYPE.findall(signals)
    return {
        "red": symbols.count("🔴"),
        "warning": symbols.count("⚠️"),
        "ok": symbols.count("✅"),
    }


def _facts_view_freshness(
    facts_view: str | None, *, today: date
) -> tuple[str, str | None, int | None]:
    if facts_view is None:
        return "missing", None, None
    match = _LAST_REVIEWED.search(facts_view)
    if match is None:
        return "invalid", None, None
    try:
        reviewed = date.fromisoformat(match.group(1))
    except ValueError:
        return "invalid", None, None
    age_days = max((today - reviewed).days, 0)
    if age_days > 60:
        return "stale_60d", reviewed.isoformat(), age_days
    if age_days > 30:
        return "stale_30d", reviewed.isoformat(), age_days
    return "current", reviewed.isoformat(), age_days


def inspect_control_health(
    domain_root: Path, *, today: date | None = None
) -> ControlHealth:
    """Inspect stable controller inputs without running controller subcommands."""
    if not domain_root.is_dir():
        raise ValueError("domain root is missing")
    observed_on = datetime.now(UTC).date() if today is None else today
    signals = _regular_text(domain_root / "_control" / "signals.md")
    facts_status, reviewed_on, facts_age_days = _facts_view_freshness(
        _regular_text(domain_root / "_entities" / "facts.md"), today=observed_on
    )
    counts = (
        _signal_counts(signals)
        if signals is not None
        else {
            "red": 0,
            "warning": 0,
            "ok": 0,
        }
    )
    if signals is None or facts_status in {"missing", "invalid"}:
        status = "invalid"
    elif counts["red"]:
        status = "critical"
    elif counts["warning"] >= 3 or facts_status in {"stale_30d", "stale_60d"}:
        status = "attention"
    else:
        status = "ok"
    return ControlHealth(status, counts, facts_status, reviewed_on, facts_age_days)


def main(argv: Sequence[str] | None = None) -> int:
    """Expose the bounded control-input projection as a Runtime owner command."""
    parser = argparse.ArgumentParser(prog="runtime-documents-control-health")
    subcommands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subcommands.add_parser("inspect")
    inspect_parser.add_argument("--domain-relative", required=True)
    args = parser.parse_args(argv)
    if args.command != "inspect":  # pragma: no cover - argparse owns this boundary
        return 2
    try:
        domain = resolve_documents_read_path(
            documents_content_root(), args.domain_relative
        )
        result = inspect_control_health(domain)
    except (DocumentsPlanePathError, OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
