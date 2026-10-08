#!/usr/bin/env python3
"""kems-sanyi.py — 三医专项进度表 → 本体数据（P2 延续）。

读取 P1 提取的三医进度表文本（/tmp/kems-p1/三医进度表.txt），
把四类任务要求（直连扩面/电子病历共享应用/检查检验结果互认/医疗电子票据）
提炼为 Requirement 实例（含子项清单），追加至沙箱本体数据 instances-20261008.yaml，
再由 P1 生成模型校验（0 违规才算入本）。

用法：kems-sanyi.py
"""
from __future__ import annotations

import pathlib
import sys

import yaml

TXT = pathlib.Path("/tmp/kems-p1/三医进度表.txt")
SBOX = pathlib.Path.home() / ".kems-pilot/卫健委-shadow"
DATA = SBOX / "_kems-pilot/data/instances-20261008.yaml"

# 四类任务要求（蒸馏自进度表表头：四类 × 子项矩阵）
CATEGORIES = {
    "REQ-SANYI-DIRECT": {
        "name": "直连扩面（预约挂号平台直连等 9 项）", "level": "区级", "field": "卫生",
        "items": ["预约挂号平台直连", "医保移动支付“京通”为入口", "“京通”挂号缴费上线",
                  "检验报告上传", "医疗影像上传", "京津冀异地医保移动支付试点",
                  "微信支付渠道接入医保移动支付", "候诊排队线上查询", "医生工作站跨院共享插件"],
    },
    "REQ-SANYI-EMR": {
        "name": "电子病历共享应用（门急诊/住院/体检病历等 5 项）", "level": "区级", "field": "卫生",
        "items": ["门急诊病历", "住院病历", "体检报告", "新增字段技术改造"],
    },
    "REQ-SANYI-XH": {
        "name": "检查检验结果互认（检查/检验互认 2 项）", "level": "区级", "field": "卫生",
        "items": ["检查结果互认", "检验结果互认"],
    },
    "REQ-SANYI-PIAO": {
        "name": "医疗电子票据（上线推广）", "level": "区级", "field": "卫生",
        "items": ["医疗电子票据"],
    },
}


def main() -> int:
    if not TXT.exists():
        print(f"MISSING_SOURCE {TXT}")
        return 1
    text = TXT.read_text(encoding="utf-8")
    # 任务矩阵统计（机构数 + 各行是否完成态）
    rows = [ln for ln in text.splitlines() if ln.strip() and ln.strip()[0].isdigit()]
    orgs = len([ln for ln in rows if "医院" in ln or "中心" in ln or "卫生" in ln])

    data = yaml.safe_load(DATA.read_text(encoding="utf-8"))
    existing = {r["id"] for r in data["instances"].get("Requirement", [])}
    added = []
    for rid, meta in CATEGORIES.items():
        if rid in existing:
            continue
        rec = {
            "id": rid, "name": meta["name"], "level": meta["level"], "field": meta["field"],
            "check_item": "；".join(meta["items"]),
            "requirement_text": f"三医专项（2023-2026）任务要求：{meta['name']}，子项 {len(meta['items'])} 项",
            "source_file": "2026年房山区“三医”领域信息化专项工作进度表（08.06）",
        }
        data["instances"].setdefault("Requirement", []).append(rec)
        added.append(rid)
    if orgs:
        data["meta_sanyi"] = {
            "orgs_in_table": orgs,
            "categories": len(CATEGORIES),
            "source": "2026年房山区“三医”领域信息化专项工作进度表（08.06）",
        }
    DATA.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"SANYI_ADDED: {added} | orgs_in_table={orgs} | total_requirements={len(data['instances'].get('Requirement', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
