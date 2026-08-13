"""Read-only, explicitly incomplete shadow of the legacy Weijian controller."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from .paths import (
    DocumentsPlanePathError,
    documents_content_root,
    resolve_documents_read_path,
)

_SCHEMA = "runtime.documents-controller-shadow.v2"
_PLANES = ("_control", "_entities", "_meta", "_runtime", "_storage", "_knowledge")
_LEGACY_RULE_IDS = (
    "CR01",
    "CR02",
    "CR03",
    "CR05",
    "CR08",
    "CR23",
    "CR24",
    "CR25",
    "CR26",
    "CR29",
    "CR30",
)
_OBSERVED_RULE_IDS = ("CR01", "CR02", "CR03", "CR05")
_UNOBSERVED_RULE_IDS = tuple(
    rule_id for rule_id in _LEGACY_RULE_IDS if rule_id not in _OBSERVED_RULE_IDS
)
_SIGNAL_TYPE = re.compile(r"(?m)^\s*(?:-\s*)?type:\s*(🔴|⚠️|✅)\s*$")
_LAST_REVIEWED = re.compile(r"(?mi)^last-reviewed:\s*(\d{4}-\d{2}-\d{2})\s*$")


@dataclass(frozen=True)
class FreshnessSummary:
    """Aggregate six-plane freshness without exposing source paths or text."""

    scanned_markdown_count: int
    stale_30_60_count: int
    stale_60_count: int
    invalid_reviewed_count: int
    unreadable_regular_file_count: int


@dataclass(frozen=True)
class ControllerShadow:
    """A non-replacement observation boundary for the legacy controller."""

    status: str
    legacy_controller_replaced: bool
    cutover_ready: bool
    legacy_rule_ids: tuple[str, ...]
    observed_rule_ids: tuple[str, ...]
    unobserved_rule_ids: tuple[str, ...]
    signal_counts: dict[str, int]
    freshness: FreshnessSummary

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["legacy_rule_ids"] = list(self.legacy_rule_ids)
        payload["observed_rule_ids"] = list(self.observed_rule_ids)
        payload["unobserved_rule_ids"] = list(self.unobserved_rule_ids)
        payload["schema"] = _SCHEMA
        return dict(sorted(payload.items()))


def _regular_markdown_files(domain_root: Path) -> Iterator[Path]:
    for plane in _PLANES:
        root = domain_root / plane
        try:
            mode = root.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError(f"controller shadow plane is unreadable: {plane}") from exc
        if not stat.S_ISDIR(mode):
            raise ValueError(
                f"controller shadow plane must be a direct directory: {plane}"
            )
        for current, directory_names, file_names in os.walk(root, followlinks=False):
            directory_names[:] = sorted(
                name for name in directory_names if not name.startswith(".")
            )
            for name in sorted(file_names):
                if not name.endswith(".md"):
                    continue
                path = Path(current) / name
                try:
                    if stat.S_ISREG(path.lstat().st_mode):
                        yield path
                except OSError:
                    yield path


def _freshness(domain_root: Path, *, today: date) -> FreshnessSummary:
    scanned = stale_30_60 = stale_60 = invalid = unreadable = 0
    for path in _regular_markdown_files(domain_root):
        try:
            text = path.read_text(encoding="utf-8")[:4096]
        except (OSError, UnicodeError):
            unreadable += 1
            continue
        match = _LAST_REVIEWED.search(text)
        if match is None:
            continue
        try:
            reviewed = date.fromisoformat(match.group(1))
        except ValueError:
            invalid += 1
            continue
        scanned += 1
        age_days = max((today - reviewed).days, 0)
        if age_days > 60:
            stale_60 += 1
        elif age_days > 30:
            stale_30_60 += 1
    return FreshnessSummary(scanned, stale_30_60, stale_60, invalid, unreadable)


def _signal_counts(domain_root: Path) -> dict[str, int]:
    try:
        signal_file = domain_root / "_control" / "signals.md"
        if not stat.S_ISREG(signal_file.lstat().st_mode):
            raise OSError("signals.md is not a regular file")
        symbols = _SIGNAL_TYPE.findall(signal_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        symbols = []
    return {
        "red": symbols.count("🔴"),
        "warning": symbols.count("⚠️"),
        "ok": symbols.count("✅"),
    }


def inspect_controller_shadow(
    domain_root: Path, *, today: date | None = None
) -> ControllerShadow:
    """Observe four safe inputs and inventory every legacy rule without execution."""
    try:
        domain_mode = domain_root.lstat().st_mode
    except OSError as exc:
        raise ValueError("domain root is missing") from exc
    if not stat.S_ISDIR(domain_mode):
        raise ValueError("domain root is missing")
    observed_on = datetime.now(UTC).date() if today is None else today
    return ControllerShadow(
        status="shadow_observed",
        legacy_controller_replaced=False,
        cutover_ready=False,
        legacy_rule_ids=_LEGACY_RULE_IDS,
        observed_rule_ids=_OBSERVED_RULE_IDS,
        unobserved_rule_ids=_UNOBSERVED_RULE_IDS,
        signal_counts=_signal_counts(domain_root),
        freshness=_freshness(domain_root, today=observed_on),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Expose an explicit shadow-only owner command for controlled comparison."""
    parser = argparse.ArgumentParser(prog="runtime-documents-controller-shadow")
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
        result = inspect_controller_shadow(domain)
    except (DocumentsPlanePathError, OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    return 1


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
