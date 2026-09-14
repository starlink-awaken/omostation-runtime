"""Read-only validation for structured Documents facts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import stat
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from .paths import (
    DocumentsPlanePathError,
    documents_content_root,
    resolve_documents_read_path,
)

_FACT_FILE = re.compile(r"^\d{2}-.+\.yaml$")
_FACT_ID = re.compile(r"^fact-\d{8}-\d{3}$")
_TYPES = frozenset(
    {
        "budget",
        "progress",
        "config",
        "event",
        "structure",
        "rule",
        "info",
        "relation",
        "indicator",
    }
)
_TRUSTS = frozenset({"confirmed", "single_source", "rumor"})
_IMPORTANCE = frozenset({"high", "medium", "low"})


@dataclass(frozen=True)
class FactAudit:
    """Stable, JSON-safe outcome of a structured facts audit."""

    status: str
    facts_total: int
    by_type: dict[str, int]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _date(value: object) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _facts_files(facts_dir: Path) -> tuple[tuple[Path, ...], tuple[str, ...]]:
    files: list[Path] = []
    errors: list[str] = []
    for path in sorted(facts_dir.iterdir()):
        if not _FACT_FILE.fullmatch(path.name):
            continue
        try:
            file_stat = path.lstat()
        except OSError as exc:
            errors.append(f"{path.name}: cannot inspect fact file: {exc}")
            continue
        if not stat.S_ISREG(file_stat.st_mode):
            errors.append(f"{path.name}: not a regular fact file")
            continue
        files.append(path)
    return tuple(files), tuple(errors)


def _validate_fact(fact: object, *, source_name: str, errors: list[str], warnings: list[str]) -> dict[str, Any] | None:
    if not isinstance(fact, dict):
        errors.append(f"{source_name}: fact must be a mapping")
        return None
    fid = fact.get("fid")
    if not isinstance(fid, str) or not _FACT_ID.fullmatch(fid):
        errors.append(f"{source_name} {fid!r}: invalid fid")
    if fact.get("type") not in _TYPES:
        errors.append(f"{source_name} {fid!r}: invalid type")
    if fact.get("trust") not in _TRUSTS:
        errors.append(f"{source_name} {fid!r}: invalid trust")
    if fact.get("importance") not in _IMPORTANCE:
        errors.append(f"{source_name} {fid!r}: invalid importance")
    for field in ("statement", "summary"):
        if not isinstance(fact.get(field), str) or not fact[field].strip():
            errors.append(f"{source_name} {fid!r}: {field} is required")
    verified_at = _date(fact.get("verified_at"))
    expiry = _date(fact.get("expiry"))
    if verified_at is None or expiry is None:
        errors.append(f"{source_name} {fid!r}: verified_at and expiry must be dates")
    elif verified_at > expiry:
        errors.append(f"{source_name} {fid!r}: verified_at exceeds expiry")
    entity_ids = fact.get("entity_ids")
    if not isinstance(entity_ids, list) or not entity_ids:
        warnings.append(f"{source_name} {fid!r}: entity_ids is empty")
    return fact


def audit_facts(domain_root: Path) -> FactAudit:
    """Audit L1 YAML facts without modifying the supplied Documents domain."""
    facts_dir = domain_root / "_entities" / "facts"
    errors: list[str] = []
    warnings: list[str] = []
    if not facts_dir.is_dir():
        return FactAudit("invalid", 0, {}, ("facts directory is missing",), ())
    try:
        files, file_errors = _facts_files(facts_dir)
    except OSError as exc:
        return FactAudit("invalid", 0, {}, (f"cannot enumerate facts: {exc}",), ())
    errors.extend(file_errors)
    if not files:
        return FactAudit("invalid", 0, {}, (*errors, "no facts YAML files found"), ())

    all_facts: list[dict[str, Any]] = []
    for path in files:
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            errors.append(f"{path.name}: cannot load YAML: {exc}")
            continue
        if not isinstance(document, dict) or not isinstance(document.get("facts"), list):
            errors.append(f"{path.name}: facts must be a list")
            continue
        for fact in document["facts"]:
            validated = _validate_fact(fact, source_name=path.name, errors=errors, warnings=warnings)
            if validated is not None:
                all_facts.append(validated)

    fids = [fact.get("fid") for fact in all_facts]
    duplicates = sorted(fid for fid, count in Counter(fids).items() if count > 1)
    errors.extend(f"duplicate fid: {fid}" for fid in duplicates)
    by_type = dict(sorted(Counter(str(fact.get("type")) for fact in all_facts).items()))

    index_path = facts_dir / "_index.yaml"
    if index_path.exists():
        try:
            index = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            errors.append(f"_index.yaml: cannot load YAML: {exc}")
        else:
            if not isinstance(index, dict):
                errors.append("_index.yaml: expected mapping")
            elif index.get("facts_total") != len(all_facts):
                errors.append(f"facts_total mismatch: index={index.get('facts_total')!r}, actual={len(all_facts)}")
            elif index.get("by_type") is not None and index["by_type"] != by_type:
                errors.append("by_type mismatch between index and facts files")

    return FactAudit(
        "ok" if not errors else "invalid",
        len(all_facts),
        by_type,
        tuple(errors),
        tuple(warnings),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Expose the audit as a sandboxable, Documents-read-only owner command."""
    parser = argparse.ArgumentParser(prog="runtime-documents-facts")
    subcommands = parser.add_subparsers(dest="command", required=True)
    audit_parser = subcommands.add_parser("audit")
    audit_parser.add_argument("--domain-relative", required=True)
    args = parser.parse_args(argv)
    if args.command != "audit":  # pragma: no cover - argparse owns this boundary
        return 2
    try:
        domain = resolve_documents_read_path(documents_content_root(), args.domain_relative)
    except DocumentsPlanePathError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 2
    result = audit_facts(domain)
    print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
