#!/usr/bin/env python3
"""check-ssot-sync.py — SSOT 同步检查

检查域内 SSOT 各文件之间的计数一致性：
  1. facts/_index.yaml 的 facts_total = 各 facts 文件实际条数加总 = by_type 加总
  2. expired_active 计数与实际一致（status=active 且 expiry < 今天）
  3. ontology/instances.yaml 的 total_instances = 实际 instances 列表长度
  4. ontology/associations.yaml 的 total_edges = 实际 edges 列表长度
  5. ontology/classes.yaml 各类 instance_count 与 instances.yaml 中该 class 实际数量一致

用法：
  python3 check-ssot-sync.py --root <域根>
退出码：0=全部通过，1=存在不一致。
"""
import argparse
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

FACTS_GLOB = "*.yaml"


def resolve_root(raw):
    p = Path(raw).expanduser().resolve()
    if not p.is_dir():
        sys.exit(f"❌ 域根不存在: {p}")
    return p


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main():
    ap = argparse.ArgumentParser(description="SSOT 同步计数一致性检查")
    ap.add_argument("--root", required=True, help="域根绝对路径")
    args = ap.parse_args()
    domain = resolve_root(args.root)

    facts_dir = domain / "_entities" / "facts"
    ont_dir = domain / "_entities" / "ontology"
    today = date.today()

    passed = 0
    failed = 0

    def ok(msg):
        nonlocal passed
        passed += 1
        print(f"✅ {msg}")

    def bad(msg):
        nonlocal failed
        failed += 1
        print(f"❌ {msg}")

    print("=" * 60)
    print("🔍 SSOT 同步计数一致性检查")
    print(f"   域: {domain}")
    print(f"   日期: {today}")
    print("=" * 60)

    # ── 1. facts/_index.yaml 三方对账 ──
    print("\n[1] facts 计数对账")
    index_path = facts_dir / "_index.yaml"
    if not index_path.is_file():
        bad(f"facts/_index.yaml 不存在: {index_path}")
    else:
        index = load_yaml(index_path)
        declared_total = index.get("facts_total", -1)
        declared_by_type = index.get("by_type", {}) or {}

        # 实际逐文件统计
        actual_per_file = {}
        actual_by_type = {}
        actual_expired_active = 0
        for f in sorted(facts_dir.glob(FACTS_GLOB)):
            if f.name == "_index.yaml":
                continue
            data = load_yaml(f)
            facts = data.get("facts", []) or []
            actual_per_file[f.name] = len(facts)
            for fact in facts:
                t = fact.get("type", "unknown")
                actual_by_type[t] = actual_by_type.get(t, 0) + 1
                # expired_active: status=active 且 expiry < 今天
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
                            actual_expired_active += 1
                    except (ValueError, TypeError):
                        pass

        actual_total = sum(actual_per_file.values())
        declared_per_file_sum = sum((index.get("per_file", {}) or {}).values())
        declared_by_type_sum = sum(declared_by_type.values())

        if declared_total == actual_total:
            ok(f"facts_total={declared_total} = 实际加总={actual_total}")
        else:
            bad(f"facts_total={declared_total} ≠ 实际加总={actual_total}")

        if declared_total == declared_per_file_sum:
            ok(f"facts_total={declared_total} = per_file 加总={declared_per_file_sum}")
        else:
            bad(f"facts_total={declared_total} ≠ per_file 加总={declared_per_file_sum}")

        if declared_total == declared_by_type_sum:
            ok(f"facts_total={declared_total} = by_type 加总={declared_by_type_sum}")
        else:
            bad(f"facts_total={declared_total} ≠ by_type 加总={declared_by_type_sum}")

        # by_type 分类逐项
        for t, cnt in actual_by_type.items():
            dc = declared_by_type.get(t)
            if dc == cnt:
                ok(f"by_type[{t}]={dc}")
            else:
                bad(f"by_type[{t}] 声明={dc} ≠ 实际={cnt}")

        # per_file 逐项
        for fn, cnt in actual_per_file.items():
            dc = (index.get("per_file", {}) or {}).get(fn)
            if dc == cnt:
                ok(f"per_file[{fn}]={cnt}")
            else:
                bad(f"per_file[{fn}] 声明={dc} ≠ 实际={cnt}")

        # expired_active
        declared_expired = index.get("expired_active", -1)
        if declared_expired == actual_expired_active:
            ok(f"expired_active={declared_expired} = 实际={actual_expired_active}")
        else:
            bad(f"expired_active={declared_expired} ≠ 实际={actual_expired_active}")

    # ── 2. instances.yaml 总数 ──
    print("\n[2] ontology 实例/边计数")
    inst_path = ont_dir / "instances.yaml"
    if not inst_path.is_file():
        bad("ontology/instances.yaml 不存在")
    else:
        inst = load_yaml(inst_path)
        declared_inst = inst.get("total_instances", -1)
        actual_inst = len(inst.get("instances", []) or [])
        if declared_inst == actual_inst:
            ok(f"total_instances={declared_inst} = 实际列表长度={actual_inst}")
        else:
            bad(f"total_instances={declared_inst} ≠ 实际列表长度={actual_inst}")

    # ── 3. associations.yaml 边数 ──
    assoc_path = ont_dir / "associations.yaml"
    if not assoc_path.is_file():
        bad("ontology/associations.yaml 不存在")
    else:
        assoc = load_yaml(assoc_path)
        declared_edges = assoc.get("total_edges", -1)
        actual_edges = len(assoc.get("edges", []) or [])
        if declared_edges == actual_edges:
            ok(f"total_edges={declared_edges} = 实际列表长度={actual_edges}")
        else:
            bad(f"total_edges={declared_edges} ≠ 实际列表长度={actual_edges}")

    # ── 4. classes.yaml 各类 instance_count vs 实际 ──
    print("\n[3] classes 各类 instance_count 对账")
    cls_path = ont_dir / "classes.yaml"
    if not cls_path.is_file() or not inst_path.is_file():
        bad("classes.yaml 或 instances.yaml 缺失，跳过")
    else:
        cls_data = load_yaml(cls_path)
        # 统计 instances 中各 class 实际数量
        actual_by_class = {}
        for i in (inst.get("instances", []) or []):
            c = i.get("class", "?")
            actual_by_class[c] = actual_by_class.get(c, 0) + 1
        for c in (cls_data.get("classes", []) or []):
            cid = c.get("id", "?")
            declared_c = c.get("instance_count", -1)
            actual_c = actual_by_class.get(cid, 0)
            if declared_c == actual_c:
                ok(f"class {cid} instance_count={declared_c}")
            else:
                bad(f"class {cid} instance_count={declared_c} ≠ 实际={actual_c}")

    # ── 汇总 ──
    print("\n" + "=" * 60)
    total = passed + failed
    print(f"📊 汇总: 通过 {passed}/{total}, 失败 {failed}/{total}")
    print("=" * 60)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
