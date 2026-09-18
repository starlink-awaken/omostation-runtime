#!/usr/bin/env python3
"""kems-init.py — KEMS 域初始化（幂等）

在指定域根上创建 KEMS 六平面骨架：
  - 目录：_control / _entities / _knowledge / _storage / _runtime / _meta
  - 本体模板：_entities/ontology/ 下 9 个空 YAML
      metamodel / classes / relations / layers / instances / gaps /
      aliases / associations / constraints
  - facts 模板：_entities/facts/_index.yaml + 9 个分类空文件
      00-budget ~ 08-indicator
  - .kems/ 目录与 STATUS.md 模板

幂等：已存在的文件/目录不覆盖，只创建缺失的。
先检查域根是否存在 DOMAIN.yaml（不存在则告警）。

用法：
  python3 kems-init.py --root <域根>
退出码：0=初始化完成（或已就绪），1=失败。
"""
import argparse
import sys
from datetime import date
from pathlib import Path


def resolve_root(raw):
    p = Path(raw).expanduser().resolve()
    return p


def main():
    ap = argparse.ArgumentParser(description="KEMS 域初始化（幂等）")
    ap.add_argument("--root", required=True, help="域根绝对路径")
    args = ap.parse_args()
    domain = resolve_root(args.root)

    print("=" * 60)
    print("🏗️  KEMS 域初始化（幂等）")
    print(f"   域: {domain}")
    print("=" * 60)

    if not domain.is_dir():
        print(f"⚠️ 域根不存在，创建: {domain}")
        domain.mkdir(parents=True, exist_ok=True)

    created = 0
    existed = 0

    def mkdir(p):
        nonlocal created, existed
        if p.is_dir():
            existed += 1
        else:
            p.mkdir(parents=True, exist_ok=True)
            created += 1
            print(f"   📁 创建目录: {p.relative_to(domain)}")

    def touch(p, content):
        nonlocal created, existed
        if p.exists():
            existed += 1
        else:
            p.write_text(content, encoding="utf-8")
            created += 1
            print(f"   📄 创建文件: {p.relative_to(domain)}")

    # DOMAIN.yaml 检查
    dy = domain / "DOMAIN.yaml"
    if not dy.is_file():
        print("⚠️ 域根无 DOMAIN.yaml（建议补充域身份声明）")
    else:
        print("✅ 域根已含 DOMAIN.yaml")

    # 1. 六平面目录
    print("\n[1] 六平面目录")
    for plane in ("_control", "_entities", "_knowledge", "_storage", "_runtime", "_meta"):
        mkdir(domain / plane)
    # 子目录
    mkdir(domain / "_entities" / "ontology")
    mkdir(domain / "_entities" / "facts")
    mkdir(domain / "_entities" / "models")
    mkdir(domain / "_entities" / "entities")
    mkdir(domain / "_knowledge" / "索引目录")
    mkdir(domain / "_storage" / "01-Inbox")
    mkdir(domain / "_storage" / "06-工具" / "运行产物")

    # 2. 本体 9 个空模板
    print("\n[2] 本体模板")
    today = date.today().isoformat()
    ont_templates = {
        "metamodel.yaml": "version: 1.0\ncreated: {today}\nmetamodel: []\n",
        "classes.yaml": "version: 1.0\ncreated: {today}\nclasses: []\n",
        "relations.yaml": "version: 1.0\ncreated: {today}\nrelations: []\n",
        "layers.yaml": "version: 1.0\ncreated: {today}\nlayers: []\n",
        "instances.yaml": "version: 1.0\ntotal_instances: 0\ncreated: {today}\ninstances: []\n",
        "gaps.yaml": "version: 1.0\ncreated: {today}\ngaps: []\n",
        "aliases.yaml": "version: 1.0\ncreated: {today}\naliases: []\nviews: []\n",
        "associations.yaml": "version: 1.0\ntotal_edges: 0\ncreated: {today}\nedges: []\n",
        "constraints.yaml": "version: 1.0\ncreated: {today}\nexistence: []\nattribute: []\nrelation: []\nlifecycle: []\nintegrity: []\n",
    }
    for fn, content in ont_templates.items():
        touch(domain / "_entities" / "ontology" / fn, content.format(today=today))

    # 3. facts 模板
    print("\n[3] facts 模板")
    fact_types = [
        ("00-budget", "budget"), ("01-progress", "progress"), ("02-config", "config"),
        ("03-event", "event"), ("04-structure", "structure"), ("05-rule", "rule"),
        ("06-info", "info"), ("07-relation", "relation"), ("08-indicator", "indicator"),
    ]
    fact_names = [f"{fn}.yaml" for fn, _ in fact_types]
    index_lines = [
        "facts_total: 0",
        f"generated_at: '{today}'",
        "by_type: {}",
        "per_file:",
    ]
    index_lines.extend([f"  {name}: 0" for name in fact_names])
    index_lines.extend([
        f"last_check: '{today}'",
        "last_check_result: OK",
        "expired_active: 0",
        "",
    ])
    touch(domain / "_entities" / "facts" / "_index.yaml", "\n".join(index_lines))
    for fn, t in fact_types:
        touch(domain / "_entities" / "facts" / f"{fn}.yaml",
              f"# facts · {t}\nfacts: []\n")

    # 4. .kems/ 目录与 STATUS.md
    print("\n[4] .kems/ 声明层")
    mkdir(domain / ".kems")
    touch(domain / ".kems" / "STATUS.md",
          f"# KEMS 域状态\n\n- 初始化: {today}\n- 状态: initialized\n- 工具链: kems-v2 (--root 参数化)\n")

    print("\n" + "=" * 60)
    print(f"✅ 初始化完成：新建 {created} 项，已存在 {existed} 项（幂等跳过）")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    main()
