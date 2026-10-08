#!/usr/bin/env python3
"""kems-frontmatter.py — frontmatter 补全治理（闭环 intake 全域 FAIL）。

背景：12 域验收发现全部域 _control/STATUS.md|TIMELINE.md 缺 frontmatter
（title/date/status/owner 四字段契约），intake 正样本 12/12 FAIL——
这是机器发现的真实结构缺口。本工具负责补全（治理动作，非实现下沉）。

规则（补丁+证据纪律）：
  1) 只处理 .md 文件（YAML 无 frontmatter 概念，不适用）；
  2) 默认 --dry-run（只输出清单与建议头，不写盘）；
  3) --apply 时先备份原文件为 <file>.bak-20261009 再写头；
  4) 已有 frontmatter 只补缺字段，不改已有字段值；无 frontmatter 则生成完整头；
  5) date 用文件 mtime（真实证据，不臆造）；owner 用 DOMAIN.yaml 的 owner（无则 夏明星）；
     status 保留原值（无则 active）。
验收：补全后重跑 kems-pipe-accept.py，intake 正样本应转 PASS。

用法：kems-frontmatter.py --domain <id|all> [--apply]
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
import time

import yaml

REG = pathlib.Path.home() / "Documents/@公共/_control/L4-DOMAIN-REGISTRY.yaml"
REG_BASE = REG.parent
BACKUP_TAG = "bak-20261009"
TARGETS = ("STATUS.md", "TIMELINE.md")


def resolve(rel: str) -> pathlib.Path:
    return (REG_BASE / rel).resolve().parent


def current_frontmatter(text: str) -> tuple[bool, dict[str, str]]:
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return False, {}
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"^(\w+)\s*:\s*(.*)$", line)
        if mm:
            fields[mm.group(1)] = mm.group(2).strip().strip('"\'')
    return True, fields


def build_header(fm: dict[str, str], title: str, mtime: str, owner: str) -> str:
    out = dict(fm)
    out.setdefault("title", title)
    out.setdefault("date", mtime)
    out.setdefault("status", "active")
    out.setdefault("owner", owner)
    lines = ["---"]
    for k in ("title", "date", "status", "owner"):
        lines.append(f"{k}: {out[k]}")
    for k, v in out.items():
        if k not in ("title", "date", "status", "owner"):
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    reg = yaml.safe_load(REG.read_text(encoding="utf-8"))
    entries = [e for e in reg["manifests"] if e["id"] == args.domain or args.domain == "all"]
    changed, skipped = 0, 0
    for e in entries:
        dom = resolve(e["path"])
        # owner 从 DOMAIN.yaml 推断（仅 owner 字段，否则回退用户名）
        owner = "夏明星"
        dy = dom / "DOMAIN.yaml"
        if dy.exists():
            dd = yaml.safe_load(dy.read_text(encoding="utf-8")) or {}
            owner = dd.get("owner") or owner
        for t in TARGETS:
            p = dom / "_control" / t
            if not p.exists():
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            has, fm = current_frontmatter(text)
            missing = [k for k in ("title", "date", "status", "owner") if k not in fm]
            if has and not missing:
                continue
            mtime = time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime))
            title = p.stem
            header = build_header(fm, title, mtime, owner)
            body = text[text.find("---", 3) + 3:] if has else text
            if not body.lstrip("\n").startswith("#"):
                body = "\n" + body
            if args.apply:
                # 始终先副本备份（补丁+证据纪律），再写头
                bak = p.with_name(f"{t}.{BACKUP_TAG}")
                if not bak.exists():
                    bak.write_text(text, encoding="utf-8")
                p.write_text(header + "\n" + body.lstrip("\n"), encoding="utf-8")
            changed += 1
            print(f"{'[APPLY]' if args.apply else '[DRY]'} {e['id']}/{t}: 缺={missing or '整体'} -> {title}@{mtime} owner={owner}")
        skipped += 1
    print(f"SUMMARY: {args.domain} 域数={len(entries)} 文件改动={changed}")
    print("提示: 验收请重跑 kems-pipe-accept.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
