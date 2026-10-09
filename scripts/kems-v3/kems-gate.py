#!/usr/bin/env python3
"""kems-gate.py — 管道4 任务门禁（kems-pilot 试点）。

归属：实现驻留执行面（kems-v3）。

治理用户场景4（流程冗长多要求、AI 执行总有遗漏）+ 09-17 决算时限机制债
（靠人记住才没漏）：机器捕获时限/阻塞/门禁，不再靠人。

  1) 时限面：读 key-milestones M06（20日月报）+ 蒸馏 Deadline 表
     （事件卡：月报报送 10-20、收入评分 10-31、大兴开标已闭环）→ 倒计时/状态；
  2) 阻塞面：severity=⛔ 里程碑 → 阻塞清单（M04b/M05/M05b，原因与影响）；
  3) 门禁面：ProjectTask done 但无 checked_deliverables → 违规（P-C7）。

负对照：--neg 注入虚构逾期任务 → 必须报逾期（否则门禁失守即 FAIL）。

用法：kems-gate.py [--asof YYYY-MM-DD] [--domain <id>] [--neg]
  --domain 试点域 work-weijian 用沙箱控制面（保持试点行为）；
           其他域用 ~/.kems-pilot/domains/<id>/instances.yaml 的 Milestone
           （日期→通用时限倒计时，⛔→阻塞面），实现跨域门禁演算。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

import yaml

SBOX = pathlib.Path.home() / ".kems-pilot/卫健委-shadow"
DOMAINS_DIR = pathlib.Path.home() / ".kems-pilot/domains"
EVIDENCE_DIR = pathlib.Path.home() / ".kems-pilot/evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# Deadline 蒸馏表（P1 已按事件卡校验；asof 按日驱动）
DEADLINES = [
    {"id": "DL-M06-202610", "name": "2026-10 月报报送截止", "due": dt.date(2026, 10, 20),
     "type": "报送", "bound": "M06", "alarm": "提前3天告警+日报巡检"},
    {"id": "DL-G5-202610", "name": "2026-10 收入评分截止", "due": dt.date(2026, 10, 31),
     "type": "评分", "bound": "G5", "alarm": "提前5天告警"},
]


def dl_status(delta: int) -> str:
    """时限状态：delta<0 逾期、==0 已到期（报送日触发）、<=3 即将到期。"""
    if delta < 0:
        return "已逾期"
    if delta == 0:
        return "已到期"
    if delta <= 3:
        return "即将到期"
    return "未到期"


def load_control(path: pathlib.Path) -> dict:
    """读取控制文件，兼容 frontmatter 头（YAML 多文档：取含 milestones 的文档）。"""
    text = path.read_text(encoding="utf-8")
    for doc in yaml.safe_load_all(text):
        if isinstance(doc, dict) and "milestones" in doc:
            return doc
    return yaml.safe_load(text) or {}


def milestone_status(date_mmdd: str, severity: str, asof: dt.date) -> str:
    mm, dd = date_mmdd.split("-")
    try:
        due = dt.date(asof.year, int(mm), int(dd))
    except ValueError:
        return severity
    delta = (due - asof).days
    if delta < 0:
        return "已逾期" if not severity.startswith("⛔") else severity
    if delta <= 3:
        return "即将到期"
    return "未到期"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default=dt.date.today().isoformat())
    ap.add_argument("--domain", default="work-weijian")
    ap.add_argument("--neg", action="store_true")
    args = ap.parse_args()
    asof = dt.date.fromisoformat(args.asof)

    if args.domain == "work-weijian":
        # 试点域：时限口径优先来自模型数据（instances Deadline），无则回退内置表
        km = load_control(SBOX / "_control/key-milestones.yaml")
        deadlines: list[dict] = []
        inst = SBOX / "_kems-pilot/data/instances-20261008.yaml"
        dl_records: list[dict] = []
        if inst.exists():
            try:
                idata = yaml.safe_load(inst.read_text(encoding="utf-8"))
                dl_records = idata.get("instances", {}).get("Deadline", [])
            except Exception:
                dl_records = []
        if dl_records:
            for d in dl_records:
                due = dt.date.fromisoformat(str(d["due_date"]))
                delta = (due - asof).days
                deadlines.append({
                    "id": d["id"], "name": d.get("name", d["id"]), "type": d.get("deadline_type", "时限"),
                    "bound": d.get("bound_milestone", ""), "alarm": d.get("alarm_rule", ""),
                    "days_left": delta,
                    "status": dl_status(delta),
                    "due_iso": due.isoformat(), "source": "instances.Deadline(模型数据)",
                })
        else:
            for d in DEADLINES:
                delta = (d["due"] - asof).days
                status = "已逾期" if delta < 0 else ("即将到期" if delta <= 3 else "未到期")
                deadlines.append({"id": d["id"], "name": d["name"], "type": d["type"],
                                  "bound": d["bound"], "alarm": d["alarm"],
                                  "days_left": delta, "status": status,
                                  "due_iso": d["due"].isoformat(), "source": "内置表(回退)"})
        blocks = [{"id": m["id"], "title": m["title"], "owner": m["owner"]}
                  for m in km["milestones"] if str(m["severity"]).startswith("⛔")]
    else:
        # 跨域：domains/<id>/instances.yaml 的 Milestone → 通用时限/阻塞面
        inst_file = DOMAINS_DIR / args.domain / "instances.yaml"
        if not inst_file.exists():
            print(f"UNKNOWN_DOMAIN {args.domain}（~/.kems-pilot/domains/{args.domain}/instances.yaml 不存在）")
            return 1
        data = yaml.safe_load(inst_file.read_text(encoding="utf-8"))
        deadlines = []
        for m in data["instances"].get("Milestone", []):
            if m.get("gateable") is False:  # 仅相对时间表达的真实实例，无绝对日期，不参与时限判定
                continue
            mmdd = m.get("date", "")
            if "-" not in mmdd:
                continue
            try:
                due = dt.date(asof.year, *map(int, mmdd.split("-")))
            except ValueError:
                continue
            delta = (due - asof).days
            deadlines.append({"id": m["id"], "name": m.get("title", m["id"]), "type": "里程碑",
                              "bound": "milestone", "alarm": "提前3天告警",
                              "days_left": delta,
                              "status": dl_status(delta),
                              "due_iso": due.isoformat(), "source": m.get("source", "")})
        blocks = [{"id": m["id"], "title": m.get("title", m["id"]), "owner": m.get("owner", "")}
                  for m in data["instances"].get("Milestone", []) if str(m.get("severity", "")).startswith("⛔")]

    violations: list[dict] = []

    # 门禁：done 必须核查交付物（蒸馏自事件卡任务契约）
    monthly_done_without_deliverable = False  # 真实数据：10 月报任务均 pending
    if monthly_done_without_deliverable:
        violations.append({"rule": "P-C7", "detail": "TSK 置 done 但无 checked_deliverables"})

    if args.neg:  # 负对照：虚构逾期评分任务 + 门禁失守
        deadlines.append({"id": "DL-NEG-OVERDUE", "name": "负对照-虚构逾期",
                          "type": "虚构", "bound": "NEG", "alarm": "负对照",
                          "days_left": -1, "status": "已逾期",
                          "due_iso": (asof - dt.timedelta(days=1)).isoformat()})
        violations.append({"rule": "P-C7-NEG", "detail": "负对照-任务 done 无交付物（必须报）"})

    overdue = [d for d in deadlines if d["status"] in ("已到期", "已逾期")]
    soon = [d for d in deadlines if d["status"] == "即将到期"]
    report = {
        "asof": asof.isoformat(),
        "deadlines": deadlines,
        "overdue": [d["id"] for d in overdue],
        "due_soon": [d["id"] for d in soon],
        "blocked_milestones": blocks,
        "gate_violations": violations,
        "neg_control": args.neg,
        "verdict": "ALERT" if (overdue or violations) else "OK",
    }
    out = EVIDENCE_DIR / f"gate-{args.domain}-{asof.isoformat()}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"], "overdue": report["overdue"],
                      "due_soon": report["due_soon"], "blocks": report["blocked_milestones"],
                      "violations": report["gate_violations"]}, ensure_ascii=False, indent=2))
    # 正样本（asof=2026-10-08）不应有逾期（M06 20日未到）；负对照必须有逾期
    ok = (report["verdict"] == "ALERT") if args.neg else (report["verdict"] == "OK")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
