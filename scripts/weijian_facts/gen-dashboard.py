"""Render the portable facts portion of the Weijian session dashboard."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import yaml


def _facts_total(domain_root: Path) -> int:
    index = domain_root / "_entities" / "facts" / "_index.yaml"
    if not index.exists():
        return 0
    try:
        document = yaml.safe_load(index.read_text(encoding="utf-8")) or {}
        return int(document.get("facts_total", 0))
    except (OSError, TypeError, ValueError, yaml.YAMLError):
        return 0


def _expiring(domain_root: Path) -> list[tuple[str, str]]:
    today = dt.datetime.now(dt.UTC).date()
    items: list[tuple[str, str]] = []
    for path in sorted((domain_root / "_entities" / "facts").glob("[0-9][0-9]-*.yaml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        for fact in document.get("facts", []):
            if not isinstance(fact, dict) or not isinstance(fact.get("expiry"), str):
                continue
            try:
                expiry = dt.date.fromisoformat(fact["expiry"])
            except ValueError:
                continue
            if 0 <= (expiry - today).days <= 45:
                title = str(fact.get("summary") or fact.get("statement") or "")
                items.append((expiry.isoformat(), title[:40]))
    return sorted(items)[:8]


def render(domain_root: Path) -> str:
    today = dt.datetime.now(dt.UTC).date().isoformat()
    total = _facts_total(domain_root)
    expiring = _expiring(domain_root)
    lines = [
        "# 卫健委信息中心 · 会话 Dashboard",
        "",
        f"> **生成：** {today} | Workspace Runtime 手工维护工具",
        "",
        "## 知识资产",
        "",
        "| 资产 | 数量 | 位置 |",
        "|------|:----:|------|",
        f"| 事实基座 | **{total}** 条 | `_entities/facts/`（YAML SSOT） |",
        "",
        "## 运行边界",
        "",
        "- 日常审计：`runtime documents run documents-weijian-facts-audit --json`。",
        "- 本看板由 Workspace Runtime 的手工维护脚本生成；不会由 Documents 控制器自动执行。",
    ]
    if expiring:
        lines.extend(
            [
                "",
                "## 事实到期预警（45 天内）",
                "",
                "| 到期日 | 事实 |",
                "|--------|------|",
            ]
        )
        lines.extend(f"| {expiry} | {title} |" for expiry, title in expiring)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path, help="Documents 域根目录")
    parser.add_argument(
        "--out", type=Path, help="输出路径（默认 _control/DASHBOARD.md）"
    )
    args = parser.parse_args()
    domain = args.root.expanduser().resolve()
    output = (
        args.out.expanduser().resolve()
        if args.out
        else domain / "_control" / "DASHBOARD.md"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(domain), encoding="utf-8")
    print(f"generated {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
