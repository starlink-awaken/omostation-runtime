#!/usr/bin/env python3
"""kems-artifact.py — 管道3 产物契约（kems-pilot 试点）。

归属：实现驻留执行面（kems-v3）。

治理用户场景3（文档生成位置随机、格式不合规）：对照 Deliverable 契约
（format_req/destination 非空 + 落点目录存在 + 命名规范），产物生成/落盘前先校验。
契约源=Deliverable M2（P1 建模），命令侧可传契约参数，也可后续接 MCP 读契约表。

负对照：--neg 缺格式要求/落点不存在 → 必须拒绝（契约失守即 FAIL）。

用法：kems-artifact.py --check <交付物ID> --name <名称> --path <文件或落点> \
       [--format-req <格式要求>] [--destination <落点目录>] [--neg]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

EVIDENCE_DIR = pathlib.Path.home() / ".kems-pilot/evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# 落点目录必须存在的白名单（试点阶段；P3 后由契约表驱动）
KNOWN_DESTINATIONS = {
    "月报": str(pathlib.Path.home() / "Documents/@工作文档/卫健委/_storage/05-交付区"),
    "交付区": str(pathlib.Path.home() / "Documents/@公共/_storage/05-交付区"),
    "申报区": str(pathlib.Path.home() / "Documents/@工作文档/卫健委/_storage/05-交付区/02-新建项目立项与初设"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", required=True, help="交付物 ID")
    ap.add_argument("--name", required=True)
    ap.add_argument("--path", required=True, help="产物路径或文件名")
    ap.add_argument("--format-req", default="")
    ap.add_argument("--destination", default="")
    ap.add_argument("--neg", action="store_true")
    args = ap.parse_args()

    violations: list[str] = []
    if not args.format_req.strip():
        violations.append("format_req 缺失（产物契约无格式要求）")
    if not args.destination.strip():
        violations.append("destination 缺失（产物落点未契约化）")
    elif args.destination in KNOWN_DESTINATIONS:
        if not pathlib.Path(KNOWN_DESTINATIONS[args.destination]).is_dir():
            violations.append(f"落点目录不存在: {KNOWN_DESTINATIONS[args.destination]}")
    else:
        if not pathlib.Path(args.destination).is_dir():
            violations.append(f"落点目录不存在: {args.destination}")
    if not re.search(r"^\d{4}-\d{2}-\d{2}", args.name):
        violations.append("命名不合规：产物名应以 YYYY-MM-DD 开头")

    verdict = "REJECT" if violations else "OK"
    record = {
        "deliverable": args.check, "name": args.name, "path": args.path,
        "violations": violations, "neg_control": args.neg, "verdict": verdict,
    }
    out = EVIDENCE_DIR / f"artifact-{args.check}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "violations": violations}, ensure_ascii=False, indent=2))
    # 正样本必须 OK；负对照必须 REJECT
    ok = (verdict == "REJECT") if args.neg else (verdict == "OK")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
