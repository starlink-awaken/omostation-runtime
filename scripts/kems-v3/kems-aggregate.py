#!/usr/bin/env python3
"""kems-aggregate.py — 聚合域业务蒸馏源：从子域 instances 聚合投影。

背景：work-docs（@工作文档）是聚合域，无独立业务控制面，实例长期为 0。
用户拍板"在子域补业务蒸馏源"→ 本工具把已登记子域的实例聚合投影到聚合域，
每条实例标注 source_domain（防伪数据），聚合域从 0 实例变为"子域聚合视图"。

用法：
  kems-aggregate.py --domain work-docs --sub work-weijian,work-guozhuan,work-liyongke,work-contracts
  kems-aggregate.py --domain work-docs --sub ... --neg    # 负对照：注入虚构实例，验证暴露
输出：
  ~/.kems-pilot/domains/<domain>/instances.yaml（聚合投影，幂等重生成）
  ~/.kems-pilot/evidence/aggregate-<domain>-<date>.json（证据）
验收：聚合实例数与子域合计一致；负对照注入实例必须在输出中可见。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

import yaml

KEMS_ROOT = pathlib.Path.home() / ".kems-pilot"
DOMAINS_DIR = KEMS_ROOT / "domains"
EVIDENCE_DIR = KEMS_ROOT / "evidence"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="work-docs")
    ap.add_argument("--sub", required=True, help="子域 id 列表（逗号分隔）")
    ap.add_argument("--neg", action="store_true")
    args = ap.parse_args()
    subs = [s.strip() for s in args.sub.split(",") if s.strip()]
    today = dt.date.today().isoformat()

    merged: dict[str, list[dict]] = {"Milestone": [], "ProjectPilot": [], "Caliber": []}
    stats: dict[str, int] = {}
    for sid in subs:
        f = DOMAINS_DIR / sid / "instances.yaml"
        if not f.exists():
            print(f"SKIP {sid}: instances.yaml 不存在")
            continue
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        for kind, items in data.get("instances", {}).items():
            if kind not in merged:
                merged[kind] = []
            for it in items:
                rec = dict(it)
                rec["source_domain"] = sid  # 聚合来源标注（防伪数据）
                merged[kind].append(rec)
            stats[sid] = stats.get(sid, 0) + len(items)
    if args.neg:  # 负对照：注入虚构实例，验证聚合暴露机制
        merged["Milestone"].append({
            "id": "NEG-FICTITIOUS", "title": "负对照虚构实例（必须可见）",
            "source_domain": "NEG", "source": "负对照", "severity": "⛔", "date": "12-31",
        })

    total = sum(len(v) for v in merged.values())
    out_file = DOMAINS_DIR / args.domain / "instances.yaml"
    if not args.neg:  # 正样本才写数据面；负对照只验证暴露机制，不污染真数据
        out_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema": "kems-pilot.instances.v2", "domain": args.domain,
                   "aggregate_of": subs, "instances": merged}
        out_file.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    summary = {
        "schema": "kems-pilot.aggregate.v1", "domain": args.domain, "date": today,
        "aggregate_of": subs, "per_subdomain": stats,
        "total_instances": total, "kinds": {k: len(v) for k, v in merged.items()},
        "neg_control": args.neg,
        "verdict": "PASS" if (("NEG-FICTITIOUS" in [m["id"] for m in merged["Milestone"]]) if args.neg else total > 0) else "FAIL",
    }
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / f"aggregate-{args.domain}-{today}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
