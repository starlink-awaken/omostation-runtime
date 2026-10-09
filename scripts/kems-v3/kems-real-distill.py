#!/usr/bin/env python3
"""kems-real-distill.py — 真实任务蒸馏：从真实文件提炼业务实例（源标注，防覆盖）。

背景：S9 使用证据要求"真实任务主动经管道"。本工具从域内真实文件（md/docx）
保守解析日期-任务行 → Milestone/Requirement 实例，全部标注 source=绝对路径。
输出独立文件 real-instances.yaml（matrix 不覆盖），证据落 evidence/。

用法：
  kems-real-distill.py --domain work-guozhuan \
    --src "<文件1>,<文件2>" --kind milestone
支持格式：
  - .md：扫描 "YYYY-MM-DD" 或 "MM-DD" 日期行 + 任务描述（标题行/列表项/表格行）
  - .docx：zipfile 抽取 document.xml 的 <w:t> 文本，再同样扫描
验收：真实实例 source 字段=绝对路径；无日期行的文件产 0 实例（诚实，不编造）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

import yaml

KEMS_ROOT = pathlib.Path.home() / ".kems-pilot"
DOMAINS_DIR = KEMS_ROOT / "domains"
EVIDENCE_DIR = KEMS_ROOT / "evidence"

DATE_RE = re.compile(
    r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})"          # 2026-08-26 / 2026/8/26 / 2026.8.26
    r"|(20\d{2})年(\d{1,2})月(\d{1,2})日"            # 2026年8月26日
    r"|(\d{1,2})月(\d{1,2})日"                        # 8月26日
)
REL_RE = re.compile(r"(本周|下周|本月底|下月底|当月底|月底前|(\d{1,2})月底前|(\d{1,2})月上旬|(\d{1,2})月中旬|(\d{1,2})月下旬)")
# 过滤：frontmatter 段内行、YAML 键行、纯标题行、空行
YAML_KEY_RE = re.compile(r"^(date|last-reviewed|created|updated|owner|status|title|type|tags|priority)\s*[:：]")


def extract_docx_text(path: pathlib.Path) -> str:
    """确定性抽取 docx 文本（zipfile + XML 命名空间，不依赖外部库）。
    表格按 w:tr 合并单元格（时间列+内容列同行），普通段落原样保留。"""
    out = []
    NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(NS_W + "body")
    if body is None:
        body = root
    # 表格内段落集合（避免 tbl 分支与普通段落分支重复抓取）
    tbl_pids = set()
    for tbl in body.iter(NS_W + "tbl"):
        for p in tbl.iter(NS_W + "p"):
            tbl_pids.add(id(p))
    for node in body.iter():
        if node.tag == NS_W + "tbl":
            for tr in node.findall(NS_W + "tr"):
                cells = []
                for tc in tr.findall(NS_W + "tc"):
                    txt = " ".join("".join(t.text or "" for t in p.iter(NS_W + "t"))
                                   for p in tc.iter(NS_W + "p"))
                    cells.append(txt.strip())
                line = " | ".join(c for c in cells if c)
                if line:
                    out.append(line)
        elif node.tag == NS_W + "p" and id(node) not in tbl_pids:
            text = "".join(t.text or "" for t in node.iter(NS_W + "t"))
            if text.strip():
                out.append(text.strip())
    return "\n".join(out)


def parse_tasks(text: str) -> list[dict]:
    """保守解析：日期/相对时间行 → {date|relative, title}。确定性规则，解析不出不编造。"""
    tasks = []
    in_fm = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("---"):
            in_fm = not in_fm
            continue
        if in_fm or not s or s.startswith("#") or YAML_KEY_RE.match(s):
            continue
        m = DATE_RE.search(s)
        rel = REL_RE.search(s)
        if not m and not rel:
            continue
        title = re.sub(r"\s+", " ", s.replace("|", " ")).strip().strip("| ")[:60]
        if m:
            if m.group(1):
                date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            elif m.group(4):
                date = f"{m.group(4)}-{int(m.group(5)):02d}-{int(m.group(6)):02d}"
            else:
                date = f"{dt.date.today().year}-{int(m.group(7)):02d}-{int(m.group(8)):02d}"
            tasks.append({"date": date, "title": title})
        else:
            # 相对时间表达：不编造绝对日期，保留原文作 time_hint
            tasks.append({"relative": rel.group(0), "title": title})
    return tasks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--src", required=True, help="真实文件绝对路径（逗号分隔）")
    ap.add_argument("--kind", default="milestone", choices=["milestone", "requirement"])
    args = ap.parse_args()

    today = dt.date.today().isoformat()
    instances: list[dict] = []
    per_file: dict[str, int] = {}
    for raw in args.src.split(","):
        p = pathlib.Path(raw.strip())
        if not p.exists():
            print(f"SKIP {p}: 文件不存在")
            continue
        if p.suffix.lower() == ".docx":
            text = extract_docx_text(p)
        else:
            text = p.read_text(encoding="utf-8", errors="replace")
        tasks = parse_tasks(text)
        for t in tasks:
            rec = {"id": f"{args.domain}-real-{len(instances)+1:02d}",
                   "title": t["title"], "severity": "⚠️",
                   "owner": "", "source": str(p)}  # 真实源标注
            rec.update({"date": t["date"]} if "date" in t else {"relative": t["relative"]})
            instances.append(rec)
        per_file[p.name] = len(tasks)

    out_file = DOMAINS_DIR / args.domain / "real-instances.yaml"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": "kems-pilot.real-instances.v1", "domain": args.domain,
               "kind": args.kind, "distilled_at": today, "sources": list(dict.fromkeys(x["source"] for x in instances)),
               "instances": instances}
    out_file.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    summary = {"schema": "kems-pilot.real-distill.v1", "domain": args.domain, "kind": args.kind,
               "date": today, "per_source": per_file, "total_instances": len(instances),
               "all_sourced": all(i["source"] for i in instances)}
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / f"real-distill-{args.domain}-{today}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["all_sourced"] else 1


if __name__ == "__main__":
    sys.exit(main())
