#!/usr/bin/env python3
"""kems-snapshot.py — KEMS 状态快照

捕获当前域状态并输出 JSON 快照：
  - facts 总数/分类计数
  - instances / edges 数
  - 模型文件数
  - 实体详表（wiki）条目数
  - inbox 文件数
  - 老化知识数（facts 中 status=active 且 expiry < 今天）

输出：
  - JSON → _storage/06-工具/运行产物/kems-snapshot-YYYYMMDD-HHMMSS.json
  - 同时打印摘要到 stdout

用法：
  python3 kems-snapshot.py --root <域根>
退出码：0=成功，1=失败。
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import yaml


def resolve_root(raw):
    p = Path(raw).expanduser().resolve()
    if not p.is_dir():
        sys.exit(f"❌ 域根不存在: {p}")
    return p


def load_yaml(path):
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def count_md(d):
    if not d.is_dir():
        return 0
    return len([p for p in d.glob("*.md") if p.is_file()])


def main():
    ap = argparse.ArgumentParser(description="KEMS 域状态快照")
    ap.add_argument("--root", required=True, help="域根绝对路径")
    args = ap.parse_args()
    domain = resolve_root(args.root)
    today = date.today()
    now = datetime.now()

    ont = domain / "_entities" / "ontology"
    facts_dir = domain / "_entities" / "facts"
    models_dir = domain / "_entities" / "models"
    entities_dir = domain / "_entities" / "entities"
    inbox = domain / "_storage" / "01-Inbox"

    # facts 统计
    facts_total = 0
    facts_by_type = Counter()
    facts_expired_active = 0
    for f in sorted(facts_dir.glob("*.yaml")):
        if f.name == "_index.yaml":
            continue
        data = load_yaml(f)
        for fact in (data.get("facts", []) or []):
            facts_total += 1
            facts_by_type[fact.get("type", "unknown")] += 1
            if fact.get("status") == "active" and fact.get("expiry"):
                try:
                    exp = fact["expiry"]
                    if isinstance(exp, str):
                        exp_d = datetime.strptime(exp, "%Y-%m-%d").date()
                    elif isinstance(exp, datetime):
                        exp_d = exp.date()
                    else:
                        exp_d = None
                    if exp_d and exp_d < today:
                        facts_expired_active += 1
                except (ValueError, TypeError):
                    pass

    # ontology 统计
    inst = load_yaml(ont / "instances.yaml")
    assoc = load_yaml(ont / "associations.yaml")
    instances_n = len(inst.get("instances", []) or [])
    edges_n = len(assoc.get("edges", []) or [])

    # 模型 / 实体详表 / inbox
    models_n = count_md(models_dir)
    entities_n = count_md(entities_dir)
    inbox_n = 0
    if inbox.is_dir():
        for p in inbox.rglob("*"):
            if p.is_file() and not p.name.startswith(".") and p.suffix in (".md", ".docx", ".xlsx", ".pdf", ".txt"):
                inbox_n += 1

    snapshot = {
        "captured_at": now.isoformat(),
        "domain_root": str(domain),
        "facts": {
            "total": facts_total,
            "by_type": dict(facts_by_type),
            "expired_active": facts_expired_active,
        },
        "ontology": {
            "instances": instances_n,
            "edges": edges_n,
        },
        "models": models_n,
        "entities_wiki_md": entities_n,
        "inbox_files": inbox_n,
    }

    # 写 JSON
    out_dir = domain / "_storage" / "06-工具" / "运行产物"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"kems-snapshot-{now.strftime('%Y%m%d-%H%M%S')}.json"
    out_path = out_dir / fname
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    # 打印摘要
    print("=" * 60)
    print("📸 KEMS 状态快照")
    print(f"   域: {domain}")
    print(f"   时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print(f"\n📊 facts: 总数={facts_total}, 过期active={facts_expired_active}")
    for t, c in sorted(facts_by_type.items()):
        print(f"     · {t}: {c}")
    print(f"\n🔗 ontology: instances={instances_n}, edges={edges_n}")
    print(f"📦 模型文件: {models_n}")
    print(f"📖 实体详表(md): {entities_n}")
    print(f"📥 inbox 文件: {inbox_n}")
    print(f"\n✅ 快照已写入: {out_path}")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    main()
