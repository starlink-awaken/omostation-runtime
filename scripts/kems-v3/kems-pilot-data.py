#!/usr/bin/env python3
"""kems-pilot-data.py — P2 重提炼迁移：真实文件 → 本体数据（kems-pilot 试点）。

归属：实现驻留执行面（kems-v3）；输出=沙箱内本体数据（数据不进 Workspace 仓库）。

从真实文件（key-milestones.yaml / 项目口径.yaml）提炼为结构化本体数据，
落盘沙箱 _kems-pilot/data/instances-20261008.yaml；随后由 kems-pilot-validate.py
读该文件跑模型校验（0 违规才算迁移闭环）。

用法：kems-pilot-data.py
"""
from __future__ import annotations

import pathlib
import sys

import yaml

SBOX = pathlib.Path.home() / ".kems-pilot/卫健委-shadow"
DATA_DIR = SBOX / "_kems-pilot/data"
OUT = DATA_DIR / "instances-20261008.yaml"

BLOCKED_NOTE = {
    "M04b": ("前置依赖 M04 经信局批复未出", "财政评审申报无法推进"),
    "M05": ("经信局审批环节卡点，领导已去协调（外部动作进行中）", "初设报送/后续流程阻塞，材料已齐备非文档缺口"),
    "M05b": ("需等经信局审批完成后发布（前置依赖明确）", "采购意向公开延后，正式公开版已齐备"),
}


def main() -> int:
    km = yaml.safe_load((SBOX / "_control/key-milestones.yaml").read_text(encoding="utf-8"))
    cal = yaml.safe_load((SBOX / "_control/项目口径.yaml").read_text(encoding="utf-8"))

    instances: dict[str, list] = {"Milestone": [], "ProjectPilot": [], "Caliber": []}
    for m in km["milestones"]:
        rec = {
            "id": m["id"], "date": m["date"], "title": m["title"],
            "severity": m["severity"], "owner": m["owner"],
            "gap_ids": m.get("gap_ids") or [], "req_files": m.get("req_files") or [],
            "note": m.get("note", ""),
            "source": "_control/key-milestones.yaml",
        }
        if str(m["severity"]).startswith("⛔") and m["id"] in BLOCKED_NOTE:
            rec["blocked_reason"], rec["impact"] = BLOCKED_NOTE[m["id"]]
        instances["Milestone"].append(rec)

    instances["ProjectPilot"].append({
        "id": "proj-data-collect",
        "full_name": cal["口径"]["项目全称"],
        "nature": cal["口径"]["项目性质"],
        "investment_wan": float(cal["口径"]["总投资万元"]),
        "software_fee_wan": float(cal["口径"]["软件开发费万元"]),
        "supervision_fee_wan": float(cal["口径"]["监理费万元"]),
        "funding_source": cal["口径"]["资金来源"],
        "institution_count": 33,
        "build_period": cal["口径"]["建设周期"],
        "owner": cal["口径"]["项目负责人"],
        "contact": cal["口径"]["联络人"],
        "supervising_leader": cal["口径"]["主管领导"],
        "parent_project": cal["口径"]["项目归属"],
        "deployment": cal["口径"]["部署环境"],
        "data_scope": cal["口径"]["数据范围"],
        "status": "经信局审核",
        "source": "_control/项目口径.yaml",
    })

    for key, value in cal["口径"].items():
        if key in ("项目性质", "项目负责人", "联络人", "主管领导"):
            continue
        instances["Caliber"].append({
            "id": f"cal-{key}", "key": key, "value": str(value),
            "project": "proj-data-collect", "source": "_control/项目口径.yaml",
            "confirm_method": "文件",
        })

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "kems-pilot.instances.v1",
        "generated": "2026-10-08",
        "provenance": "P2 重提炼迁移：真实控制面文件 → 本体数据（M2 kems-pilot 校验）",
        "instances": instances,
    }
    OUT.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    total = sum(len(v) for v in instances.values())
    print(f"WROTE {OUT} | instances={total} (Milestone={len(instances['Milestone'])}, "
          f"ProjectPilot={len(instances['ProjectPilot'])}, Caliber={len(instances['Caliber'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
