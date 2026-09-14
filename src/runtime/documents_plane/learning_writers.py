"""Explicit-apply owners for retired write-mode learning executors.

ADR-0441 primitive 2: writes to Documents are explicit_apply_only — every
mutating owner defaults to a dry-run report and requires --apply to touch
Documents. Content fragments stay inside Documents; reports carry counts and
relative paths only.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Final

import yaml

from .paths import DocumentsPlanePathError, documents_content_root, resolve_documents_read_path

_REPAIR_SCHEMA: Final = "runtime.documents-repair-cards.v1"
_INGEST_SCHEMA: Final = "runtime.documents-minerva-ingest.v1"
_CONCEPT_RELATIVE: Final = "@学习进化/_knowledge/50-concepts"
_FRONTMATTER_RE: Final = re.compile(r"\A---\s*\n(.*?)\n---\s*(\n|\Z)", re.DOTALL)
_DIR_TAGS: Final = {
    "AI与智能体": ["domain/ai", "domain/agents"],
    "认知心理": ["domain/cognitive-psychology", "domain/mind"],
}
_TYPE_KEYWORDS: Final = {
    "method": ("方法", "method", "how"),
    "fact": ("事实", "fact"),
    "concept": (),
}


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


def _concept_root(documents_root: Path, domain_relative: str) -> Path:
    raw = Path(documents_root).expanduser()
    if not raw.is_dir() or raw.is_symlink():
        raise DocumentsPlanePathError("Documents content root must be a regular directory")
    root = resolve_documents_read_path(raw.resolve(), domain_relative)
    if not root.is_dir() or root.is_symlink():
        raise DocumentsPlanePathError("learning concept root must be a regular directory")
    return root


def _cards(root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in root.rglob("*.md")
            if path.is_file() and not path.is_symlink() and path.name not in {"README.md", "INDEX.md", "_index.md"}
        )
    )


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}, text
    return (loaded if isinstance(loaded, dict) else {}), text[match.end() :]


def _infer_tags(path: Path) -> list[str]:
    for directory, tags in _DIR_TAGS.items():
        if directory in path.parts:
            return list(tags)
    return ["domain/uncategorized"]


def _infer_type(path: Path) -> str:
    stem = path.stem.lower()
    for kind, keywords in _TYPE_KEYWORDS.items():
        if any(keyword in stem for keyword in keywords):
            return kind
    return "concept"


def _render_frontmatter(fields: dict) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {item}" for item in value)
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# --- repair (frontmatter backfill, dry-run default) ------------------------


def repair_concept_cards(
    documents_root: Path,
    *,
    domain_relative: str = _CONCEPT_RELATIVE,
    apply: bool = False,
    today: date | None = None,
) -> dict[str, object]:
    """Backfill missing tags/created/knowledge_type; report aggregates, write only on apply."""

    try:
        root = _concept_root(documents_root, domain_relative)
    except DocumentsPlanePathError:
        return _unavailable(_REPAIR_SCHEMA, {"repairable": 0, "repaired": 0})
    checked_on = today or date.today()
    repairable = 0
    repaired = 0
    field_backfill: dict[str, int] = {"tags": 0, "created": 0, "knowledge_type": 0}
    for path in _cards(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fields, body = _parse_frontmatter(text)
        if not fields:
            continue  # no frontmatter → validate's L0 domain, not repair's
        missing = {
            "tags": _infer_tags(path),
            "created": datetime.fromtimestamp(path.stat().st_mtime).date().isoformat(),
            "knowledge_type": _infer_type(path),
        }
        needed = {key: value for key, value in missing.items() if not str(fields.get(key) or "").strip()}
        if not needed:
            continue
        repairable += 1
        for key in needed:
            field_backfill[key] += 1
        if apply:
            merged = {**fields, **needed}
            try:
                path.write_text(_render_frontmatter(merged) + body, encoding="utf-8")
                repaired += 1
            except OSError:
                continue
    return {
        "schema": _REPAIR_SCHEMA,
        "status": "applied" if apply else "dry_run",
        "checked_on": checked_on.isoformat(),
        "repairable": repairable,
        "repaired": repaired,
        "field_backfill": field_backfill,
        "apply": apply,
        "error": None,
    }


# --- minerva ingest (research payload → vault, explicit apply) --------------


def ingest_research(
    documents_root: Path,
    *,
    title: str,
    content: str,
    domain_relative: str = "@学习进化/_inbox",
    apply: bool = False,
    today: date | None = None,
) -> dict[str, object]:
    """Stage a research note into the vault inbox; writes only on apply."""

    if not title.strip() or not content.strip():
        return _unavailable(_INGEST_SCHEMA, {"error": "title_or_content_empty"})
    try:
        root = _concept_root(documents_root, domain_relative)
    except DocumentsPlanePathError:
        return _unavailable(_INGEST_SCHEMA)
    checked_on = today or date.today()
    safe_stem = re.sub(r"[^\w一-鿿-]+", "-", title.strip())[:60]
    target = root / f"{checked_on.isoformat()}-{safe_stem}.md"
    payload = {
        "schema": _INGEST_SCHEMA,
        "status": "applied" if apply else "dry_run",
        "checked_on": checked_on.isoformat(),
        "target_relative": str(target.relative_to(root)),
        "content_bytes": len(content.encode("utf-8")),
        "apply": apply,
        "error": None,
    }
    if apply and not target.exists():
        note = (
            "---\n"
            f"title: {title.strip()}\n"
            "knowledge_type: research-ingest\n"
            f"source: minerva-ingest\n"
            f"created: {checked_on.isoformat()}\n"
            "---\n" + content.strip() + "\n"
        )
        try:
            target.write_text(note, encoding="utf-8")
        except OSError as exc:
            payload["status"] = "unavailable"
            payload["error"] = f"write_failed: {exc.__class__.__name__}"
    return payload


# --- CLI --------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p_repair = sub.add_parser("repair", help="backfill concept-card frontmatter (dry-run default)")
    p_repair.add_argument("--domain-relative", default=_CONCEPT_RELATIVE)
    p_repair.add_argument("--apply", action="store_true")
    p_ingest = sub.add_parser("ingest", help="stage a research note into the vault inbox (dry-run default)")
    p_ingest.add_argument("--title", required=True)
    p_ingest.add_argument("--content-file", type=Path)
    p_ingest.add_argument("--domain-relative", default="@学习进化/_inbox")
    p_ingest.add_argument("--apply", action="store_true")
    for sub_parser in (p_repair, p_ingest):
        sub_parser.add_argument("--documents-root", type=Path)
    args = parser.parse_args(argv)
    root = args.documents_root or documents_content_root()
    if args.action == "repair":
        payload = repair_concept_cards(root, domain_relative=args.domain_relative, apply=args.apply)
    else:
        content = args.content_file.read_text(encoding="utf-8") if args.content_file else ""
        payload = ingest_research(
            root, title=args.title, content=content, domain_relative=args.domain_relative, apply=args.apply
        )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    status = str(payload.get("status"))
    return 0 if status in {"ok", "dry_run", "applied"} else (1 if status == "attention" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
