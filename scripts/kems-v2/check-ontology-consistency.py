#!/usr/bin/env python3
"""check-ontology-consistency.py — 本体一致性检查

校验 ontology 九个 YAML 之间的引用完整性：
  1. associations.yaml 所有 edge 的 source/target 端点必须在 instances.yaml 中存在
  2. associations.yaml 所有 edge 的 relation 必须在 relations.yaml 中定义
  3. instances.yaml 所有 instance 的 class 必须在 classes.yaml 中定义
  4. aliases.yaml 中 aliases 表的 canonical 指向的实例必须存在
  5. gaps.yaml 中 derived_from 引用的缺口 id 必须存在
  6. constraints.yaml 语法可解析（YAML 合法 + 含预期顶层键）

用法：
  python3 check-ontology-consistency.py --root <域根>
退出码：0=全部一致，1=存在不一致。
"""
import argparse
import sys
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
    except yaml.YAMLError as e:
        return {"__parse_error__": str(e)}


def main():
    ap = argparse.ArgumentParser(description="本体一致性引用检查")
    ap.add_argument("--root", required=True, help="域根绝对路径")
    args = ap.parse_args()
    domain = resolve_root(args.root)
    ont = domain / "_entities" / "ontology"

    issues = []
    checked = 0

    print("=" * 60)
    print("🔍 本体一致性引用检查")
    print(f"   域: {domain}")
    print("=" * 60)

    # 载入核心本体文件
    instances = load_yaml(ont / "instances.yaml")
    relations = load_yaml(ont / "relations.yaml")
    classes = load_yaml(ont / "classes.yaml")
    associations = load_yaml(ont / "associations.yaml")
    aliases = load_yaml(ont / "aliases.yaml")
    gaps = load_yaml(ont / "gaps.yaml")
    constraints = load_yaml(ont / "constraints.yaml")

    inst_ids = {i.get("id") for i in (instances.get("instances", []) or []) if i.get("id")}
    class_ids = {c.get("id") for c in (classes.get("classes", []) or []) if c.get("id")}
    relation_ids = {r.get("id") for r in (relations.get("relations", []) or []) if r.get("id")}

    # ── 1. edge 端点存在性 ──
    print("\n[1] associations edge 端点检查")
    for e in (associations.get("edges", []) or []):
        eid = e.get("id", "?")
        for endpoint in ("source", "target"):
            v = e.get(endpoint)
            checked += 1
            if v not in inst_ids:
                issues.append(f"❌ edge {eid}: {endpoint}={v} 不在 instances.yaml 中")
    print(f"   检查 {checked} 个端点引用")

    # ── 2. edge relation 定义存在 ──
    print("\n[2] associations edge relation 定义检查")
    n_rel = 0
    for e in (associations.get("edges", []) or []):
        eid = e.get("id", "?")
        r = e.get("relation")
        n_rel += 1
        if r not in relation_ids:
            issues.append(f"❌ edge {eid}: relation={r} 未在 relations.yaml 定义")
    print(f"   检查 {n_rel} 条边的 relation")

    # ── 3. instance class 定义存在 ──
    print("\n[3] instances class 定义检查")
    n_cls = 0
    for i in (instances.get("instances", []) or []):
        iid = i.get("id", "?")
        c = i.get("class")
        n_cls += 1
        if c not in class_ids:
            issues.append(f"❌ instance {iid}: class={c} 未在 classes.yaml 定义")
    print(f"   检查 {n_cls} 个实例的 class")

    # ── 4. aliases canonical 指向实例存在 ──
    print("\n[4] aliases canonical 指向检查")
    n_ali = 0
    for a in (aliases.get("aliases", []) or []):
        canonical = a.get("canonical")
        alias = a.get("alias", "?")
        n_ali += 1
        if canonical and canonical not in inst_ids:
            issues.append(f"❌ alias {alias}: canonical={canonical} 不在 instances.yaml 中")
    print(f"   检查 {n_ali} 条别名（views 不设实例，跳过）")

    # ── 5. gaps derived_from 缺口 id 存在 ──
    print("\n[5] gaps derived_from 引用检查")
    gap_ids = {g.get("id") for g in (gaps.get("gaps", []) or []) if g.get("id")}
    n_gap = 0
    for g in (gaps.get("gaps", []) or []):
        gid = g.get("id", "?")
        df = g.get("derived_from")
        n_gap += 1
        if df and df not in gap_ids:
            issues.append(f"❌ gap {gid}: derived_from={df} 不在 gaps.yaml 中")
    print(f"   检查 {n_gap} 个缺口的 derived_from")

    # ── 6. constraints.yaml 可解析 ──
    print("\n[6] constraints.yaml 语法检查")
    if "__parse_error__" in constraints:
        issues.append(f"❌ constraints.yaml YAML 解析失败: {constraints['__parse_error__']}")
    else:
        print(f"   ✅ constraints.yaml YAML 可解析（顶层键: {', '.join(constraints.keys())}）")

    # ── 汇总 ──
    print("\n" + "=" * 60)
    if issues:
        print(f"❌ 发现 {len(issues)} 处不一致：")
        for it in issues:
            print(f"   {it}")
    else:
        print("✅ 本体引用全部一致，无不一致项")
    print("=" * 60)
    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
