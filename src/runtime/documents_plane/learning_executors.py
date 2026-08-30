"""Read-only owners for the retired learning executors (ADR-0441 primitive 2).

Rebuilds the Documents-era learning vault tooling as Workspace-owned,
aggregate-only inspection jobs. Relative paths may appear where they are the
functional payload (search/rename), content fragments never do.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Final

import yaml

from .paths import DocumentsPlanePathError, documents_content_root, resolve_documents_read_path

_VALIDATE_SCHEMA: Final = "runtime.documents-learning-validate.v1"
_SEARCH_SCHEMA: Final = "runtime.documents-vault-search.v1"
_RENAME_SCHEMA: Final = "runtime.documents-rename-check.v1"
_EXCLUDED_NAMES: Final = frozenset({"README.md", "INDEX.md", "_index.md"})
_DEFAULT_CONCEPT_RELATIVE: Final = "@学习进化/_knowledge/50-concepts"
_FRONTMATTER_RE: Final = re.compile(r"\A---\s*\n(.*?)\n---\s*(\n|\Z)", re.DOTALL)
_REQUIRED_FIELDS: Final = ("knowledge_type", "status", "source")
_L0 = "l0_syntax_invalid"
_L1 = "l1_logic_missing_fields"
_L2 = "l2_evidence_missing"
_L3 = "l3_business_unlinked"


def _unavailable(schema: str, extra: dict[str, object] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": schema,
        "status": "unavailable",
        "checked_on": date.today().isoformat(),
        "error": "concept_root_invalid",
    }
    if extra:
        payload.update(extra)
    return payload


def _concept_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in root.rglob("*.md")
            if path.is_file() and not path.is_symlink() and path.name not in _EXCLUDED_NAMES
        )
    )


def _split_frontmatter(text: str) -> dict | None:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _resolve_concept_root(documents_root: Path, domain_relative: str) -> Path:
    raw = Path(documents_root).expanduser()
    if not raw.is_dir() or raw.is_symlink():
        raise DocumentsPlanePathError("Documents content root must be a regular directory")
    documents = raw.resolve()
    root = resolve_documents_read_path(documents, domain_relative)
    if not root.is_dir() or root.is_symlink():
        raise DocumentsPlanePathError("learning concept root must be a regular directory")
    return root


# --- validate (G18 L0-L3 aggregate rebuild) -------------------------------


def validate_concept_cards(
    documents_root: Path,
    *,
    domain_relative: str = _DEFAULT_CONCEPT_RELATIVE,
    today: date | None = None,
) -> dict[str, object]:
    """Five-gate concept-card validation, aggregate counts only (no file names)."""

    try:
        root = _resolve_concept_root(documents_root, domain_relative)
    except DocumentsPlanePathError:
        return _unavailable(_VALIDATE_SCHEMA, {"file_count": 0, "invalid_counts": _empty_invalid_counts()})
    paths = _concept_files(root)
    texts: dict[Path, str] = {}
    for path in paths:
        try:
            texts[path] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    invalid_counts = _empty_invalid_counts()
    field_missing: dict[str, int] = {field: 0 for field in _REQUIRED_FIELDS}
    for text in texts.values():
        frontmatter = _split_frontmatter(text)
        if frontmatter is None:
            invalid_counts[_L0] += 1
            continue
        missing = [field for field in _REQUIRED_FIELDS if not str(frontmatter.get(field) or "").strip()]
        if missing:
            invalid_counts[_L1] += 1
            for field in missing:
                field_missing[field] += 1
        if not re.search(r"(source|出处|来源)\s*[:：]", text):
            invalid_counts[_L2] += 1
        if not re.search(r"(\[\[|\blinks?\s*:|相关\s*:)", text):
            invalid_counts[_L3] += 1
    status = "attention" if any(invalid_counts.values()) else "ok"
    return {
        "schema": _VALIDATE_SCHEMA,
        "status": status,
        "checked_on": (today or date.today()).isoformat(),
        "file_count": len(paths),
        "invalid_counts": invalid_counts,
        "field_missing": field_missing,
        "error": None,
    }


def _empty_invalid_counts() -> dict[str, int]:
    return {_L0: 0, _L1: 0, _L2: 0, _L3: 0}


# --- vault search (relative paths only, never content) ---------------------


def search_vault(
    documents_root: Path,
    *,
    query: str,
    domain_relative: str = "@学习进化",
    limit: int = 50,
    today: date | None = None,
) -> dict[str, object]:
    """Deterministic filename/content query returning relative paths only."""

    try:
        root = _resolve_concept_root(documents_root, domain_relative)
    except DocumentsPlanePathError:
        return _unavailable(_SEARCH_SCHEMA, {"matches": [], "match_count": 0, "truncated": False})
    if not query.strip():
        return _unavailable(
            _SEARCH_SCHEMA, {"matches": [], "match_count": 0, "truncated": False, "error": "query_empty"}
        )
    matches: list[str] = []
    truncated = False
    for path in _concept_files(root):
        if len(matches) >= limit:
            truncated = True
            break
        relative = path.relative_to(root).as_posix()
        try:
            if (
                query.lower() in path.name.lower()
                or query.lower() in path.read_text(encoding="utf-8", errors="replace").lower()
            ):
                matches.append(relative)
        except OSError:
            continue
    return {
        "schema": _SEARCH_SCHEMA,
        "status": "ok",
        "checked_on": (today or date.today()).isoformat(),
        "query_terms": len(query.split()),
        "match_count": len(matches),
        "matches": matches,
        "truncated": truncated,
        "error": None,
    }


# --- rename reference scan (relative paths only) ---------------------------


def check_rename_references(
    documents_root: Path,
    *,
    old_name: str,
    domain_relative: str = "@学习进化/_knowledge",
    limit: int = 200,
    today: date | None = None,
) -> dict[str, object]:
    """Scan wikilink/plain-text references to a renamed/deleted concept name."""

    if not old_name.strip():
        return _unavailable(_RENAME_SCHEMA, {"error": "old_name_empty"})
    try:
        root = _resolve_concept_root(documents_root, domain_relative)
    except DocumentsPlanePathError:
        return _unavailable(_RENAME_SCHEMA, {"reference_count": 0, "references": []})
    references: list[str] = []
    for path in _concept_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if old_name in text and path.stem != old_name:
            references.append(path.relative_to(root).as_posix())
            if len(references) >= limit:
                break
    return {
        "schema": _RENAME_SCHEMA,
        "status": "ok" if references else "clean",
        "checked_on": (today or date.today()).isoformat(),
        "old_name_terms": 1,
        "reference_count": len(references),
        "references": references,
        "error": None,
    }


# --- CLI -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p_validate = sub.add_parser("validate")
    p_validate.add_argument("--domain-relative", default=_DEFAULT_CONCEPT_RELATIVE)
    p_search = sub.add_parser("search")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--domain-relative", default="@学习进化")
    p_search.add_argument("--limit", type=int, default=50)
    p_rename = sub.add_parser("rename-check")
    p_rename.add_argument("--old-name", required=True)
    p_rename.add_argument("--domain-relative", default="@学习进化/_knowledge")
    p_rename.add_argument("--limit", type=int, default=200)
    p_validate.add_argument("--documents-root", type=Path)
    p_search.add_argument("--documents-root", type=Path)
    p_rename.add_argument("--documents-root", type=Path)
    args = parser.parse_args(argv)
    root = args.documents_root or documents_content_root()
    if args.action == "validate":
        payload = validate_concept_cards(root, domain_relative=args.domain_relative)
    elif args.action == "search":
        payload = search_vault(root, query=args.query, domain_relative=args.domain_relative, limit=args.limit)
    else:
        payload = check_rename_references(
            root, old_name=args.old_name, domain_relative=args.domain_relative, limit=args.limit
        )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    status = str(payload.get("status"))
    return 0 if status in {"ok", "clean"} else (1 if status == "attention" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
