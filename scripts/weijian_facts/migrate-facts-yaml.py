"""One-time explicit migration from legacy facts.md to per-type YAML files."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

import yaml

TYPE_MAP = {
    "💰预算": "budget",
    "📊进度": "progress",
    "📁配置": "config",
    "📅事件": "event",
    "🏛️结构": "structure",
    "📜规则": "rule",
    "📄信息": "info",
    "👤关系": "relation",
    "📐指标": "indicator",
}
IMPORTANCE_MAP = {"🔴": "high", "🟡": "medium", "🔵": "low", "✅": "low"}
FILE_NAMES = {
    "budget": "00-budget.yaml",
    "progress": "01-progress.yaml",
    "config": "02-config.yaml",
    "event": "03-event.yaml",
    "structure": "04-structure.yaml",
    "rule": "05-rule.yaml",
    "info": "06-info.yaml",
    "relation": "07-relation.yaml",
    "indicator": "08-indicator.yaml",
}


def _summary(statement: str) -> str:
    text = re.sub(r"^[（(][^（）()]*[)）]", "", statement).strip()
    for separator in ("；", "。", "，", ";", ","):
        position = text.find(separator)
        if 0 < position <= 50:
            text = text[:position]
            break
    return text[:50] or statement[:50]


def parse_legacy(source: Path) -> list[dict[str, object]]:
    lines = source.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "## 活跃事实")
    end = next(
        i for i, line in enumerate(lines) if line.strip() == "## 事实生命周期规则"
    )
    sequence: Counter[str] = Counter()
    facts: list[dict[str, object]] = []
    for line in lines[start:end]:
        if not line.strip().startswith("|"):
            continue
        cells = [value.strip() for value in line.strip().strip("|").split("|")]
        if len(cells) < 9 or cells[0] == "事实陈述" or cells[1].startswith(":"):
            continue
        (
            statement,
            kind,
            value,
            importance,
            source_name,
            trust,
            verified,
            expiry,
            entities,
        ) = cells[:9]
        mapped_kind = TYPE_MAP.get(kind)
        if mapped_kind is None:
            continue
        date_digits = re.sub(r"\D", "", verified)[:8]
        if len(date_digits) != 8:
            date_digits = "19700101"
        sequence[date_digits] += 1
        facts.append(
            {
                "fid": f"fact-{date_digits}-{sequence[date_digits]:03d}",
                "statement": statement,
                "summary": _summary(statement),
                "type": mapped_kind,
                "value": None if value in {"", "-"} else value,
                "importance": IMPORTANCE_MAP.get(importance, "low"),
                "source": source_name,
                "trust": trust,
                "verified_at": verified,
                "expiry": expiry,
                "entity_ids": [
                    item.strip()
                    for item in entities.split(",")
                    if item.strip() and item.strip() != "-"
                ],
                "status": "active",
            }
        )
    return facts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path, help="Documents 域根目录")
    args = parser.parse_args()
    domain = args.root.expanduser().resolve()
    facts = parse_legacy(domain / "_entities" / "facts.md")
    facts_dir = domain / "_entities" / "facts"
    facts_dir.mkdir(parents=True, exist_ok=True)
    by_type = Counter(str(fact["type"]) for fact in facts)
    for kind, file_name in FILE_NAMES.items():
        selected = [fact for fact in facts if fact["type"] == kind]
        (facts_dir / file_name).write_text(
            yaml.safe_dump({"facts": selected}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    (facts_dir / "_index.yaml").write_text(
        yaml.safe_dump(
            {"facts_total": len(facts), "by_type": dict(sorted(by_type.items()))},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    print(f"migrated {len(facts)} facts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
