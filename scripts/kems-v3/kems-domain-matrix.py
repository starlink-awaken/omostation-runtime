#!/usr/bin/env python3
"""kems-domain-matrix.py — 试点模式推广：12 域覆盖矩阵（kems-pilot → 全域）。

归属：实现驻留执行面（kems-v3）；域发现源=SSOT registry
（@公共/_control/L4-DOMAIN-REGISTRY.yaml，12 域唯一真源，不手抄）。

对每域（只读探测，真数据零改动）：
  1) DOMAIN.yaml → 域元数据（id/archetype/authority/sensitivity）
  2) _control/ 控制面探测 → 存在性（key-milestones/项目口径/STATUS/TIMELINE/_meta）
  3) 骨架本体数据提炼（确定性规则，源文件标注）：
     - key-milestones.yaml → Milestone 骨架（≤6 条）
     - 项目口径.yaml     → ProjectPilot + Caliber 骨架（≤8 条）
  4) 通用 M2 模型校验（kems-pilot 类型集即通用域本体，跨域复用不复制）
输出：~/.kems-pilot/domains/<id>/instances.yaml + domains-matrix.json（覆盖矩阵）

用法：kems-domain-matrix.py
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

sys.path.append("/Users/xiamingxing/Workspace/projects/ecos/src/ecos/ssot/mof/generated/kems-pilot")
from mof_control_models import Caliber, Milestone, ProjectPilot  # noqa: E402

REGISTRY = pathlib.Path.home() / "Documents/@公共/_control/L4-DOMAIN-REGISTRY.yaml"
REG_BASE = REGISTRY.parent  # @公共/_control
OUT_DIR = pathlib.Path.home() / ".kems-pilot/domains"

MILESTONE_MAX = 10
MILESTONE_MAX_DEEP = 20
CALIBER_MAX = 8


def resolve_domain_path(rel: str) -> pathlib.Path:
    """manifest 的 path 指向 <domain>/DOMAIN.yaml，域目录取其父级。"""
    return (REG_BASE / rel).resolve().parent


def load_yaml_compat(path: pathlib.Path, want_key: str | None = None) -> dict:
    """读取 YAML，兼容 frontmatter 头（多文档：取含 want_key 的文档，否则取首个 dict）。"""
    text = path.read_text(encoding="utf-8")
    try:
        return yaml.safe_load(text) or {}
    except yaml.composer.ComposerError:
        for doc in yaml.safe_load_all(text):
            if isinstance(doc, dict) and (want_key is None or want_key in doc):
                return doc
        return {}


def probe(dom_dir: pathlib.Path) -> dict:
    meta: dict = {"control_files": {}}
    dom_yaml = dom_dir / "DOMAIN.yaml"
    if dom_yaml.exists():
        d = load_yaml_compat(dom_yaml)
        meta["domain"] = {
            "id": d.get("id"), "archetype": d.get("archetype"),
            "authority_policy": d.get("authority_policy"), "default_sensitivity": d.get("default_sensitivity"),
        }
    ctrl = dom_dir / "_control"
    for name in ("key-milestones.yaml", "项目口径.yaml", "STATUS.md", "TIMELINE.md"):
        meta["control_files"][name] = (ctrl / name).exists()
    meta["control_dir"] = ctrl.is_dir()
    meta["_meta_dir"] = (dom_dir / "_meta").is_dir()
    # 提取摘要元数据（语料统计，非业务实体——不参与 instances）
    es = ctrl / "_kems_extraction_summary.json"
    if es.exists():
        try:
            ed = json.loads(es.read_text(encoding="utf-8"))
            meta["extraction"] = {"files": ed.get("total_files"), "chars": ed.get("total_chars"),
                                  "domains_in_summary": ed.get("total_domains"),
                                  "reported": {k: v.get("total_files") for k, v in (ed.get("reports") or {}).items()}}
        except Exception:
            meta["extraction"] = {"note": "unparseable"}
    return meta


def parse_status_timeline(dom_id: str, ctrl: pathlib.Path, fname: str,
                          seen_ids: set[str]) -> list[dict]:
    """保守解析 STATUS.md/TIMELINE.md 的日期-标题行（表格行/列表行/纯文本行）→ Milestone。
    仅确定性可解析行入本体；解析不出的行忽略（诚实，不编造）。"""
    p = ctrl / fname
    out: list[dict] = []
    if not p.exists():
        return out
    text = p.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^\|?\s*(\d{4}-\d{2}-\d{2}|\d{2}-\d{2})\s*\|?\s*([^|]{2,64})", line)
        if not m:
            m = re.match(r"^\s*[-*]\s*(\d{4}-\d{2}-\d{2}|\d{2}-\d{2})\s+([^\n]{2,64})", line)
        if not m:
            m = re.match(r"^\s*(\d{4}-\d{2}-\d{2}|\d{2}-\d{2})\s*[:：]\s*([^\n]{2,64})", line)
        if not m:
            continue
        d, title = m.group(1), m.group(2).strip(" |·")
        # 排除状态标记行（STABLE/ACTIVE/🟢 等状态词开头 = 状态摘要，非任务里程碑）
        if re.match(r"^(STABLE|ACTIVE|REVIEW|DONE|🔴|🟢|🟡|状态|进展|里程碑概述|总体状态)", title):
            continue
        if "-" in d and len(d) == 10:
            d = d[5:]  # YYYY-MM-DD → MM-DD
        if not re.match(r"^\d{2}-\d{2}$", d) or not title:
            continue
        mid = f"{dom_id}-{fname.split('.')[0]}-{d.replace('-', '')}"
        if mid in seen_ids:
            continue
        seen_ids.add(mid)
        out.append({"id": mid, "date": d, "title": title[:40], "severity": "⚠️",
                    "owner": "", "source": str(p.relative_to(ctrl.parent))})
    return out


def distill(dom_id: str, dom_dir: pathlib.Path, cap: int) -> tuple[list, list, list]:
    """骨架提炼：Milestone / ProjectPilot / Caliber，全部标注源文件。
    cap：每域里程碑上限（骨架=10，--deep=20 全量）。"""
    milestones: list[dict] = []
    projects: list[dict] = []
    calibers: list[dict] = []
    seen_ids: set[str] = set()
    ctrl = dom_dir / "_control"
    km = ctrl / "key-milestones.yaml"
    if km.exists():
        data = load_yaml_compat(km, "milestones")
        for m in (data.get("milestones") or [])[:cap]:
            rec = {
                "id": f"{dom_id}-{m.get('id', 'M?')}", "date": m.get("date", "01-01"),
                "title": m.get("title", ""), "severity": str(m.get("severity", "⚠️")),
                "owner": m.get("owner", ""),
                "note": (m.get("note") or "")[:80],
                "source": str(km.relative_to(dom_dir)),
            }
            if str(m.get("severity", "")).startswith("⛔"):
                rec["blocked_reason"] = (m.get("note") or "阻塞（前置依赖）")[:60]
                rec["impact"] = "影响域内关键路径推进"
            seen_ids.add(rec["id"])
            milestones.append(rec)
    # STATUS/TIMELINE 日期行补充（保守解析）
    for fname in ("STATUS.md", "TIMELINE.md"):
        milestones.extend(parse_status_timeline(dom_id, ctrl, fname, seen_ids))
    milestones = milestones[:cap]  # 每域里程碑上限（克制）
    cal = ctrl / "项目口径.yaml"
    if cal.exists():
        data = load_yaml_compat(cal)
        kou = data.get("口径") or data.get("caliber") or data.get("项目口径") or {}
        proj_name = kou.get("项目全称") or kou.get("项目名称") or dom_id
        projects.append({
            "id": f"{dom_id}-proj-main",
            "full_name": str(proj_name),
            "nature": str(kou.get("项目性质", "专项")),
            "investment_wan": float(kou["总投资万元"]) if str(kou.get("总投资万元", "")).replace(".", "").isdigit() else None,
            "owner": str(kou.get("项目负责人", "")),
            "build_period": str(kou.get("建设周期", "")),
            "status": "经信局审核" if "经信局" in str(kou) else "实施中",
            "source": str(cal.relative_to(dom_dir)),
        })
        for key, val in list(kou.items())[:CALIBER_MAX]:
            if key in ("项目性质", "项目负责人", "项目全称"):
                continue
            calibers.append({
                "id": f"{dom_id}-cal-{key}", "key": key, "value": str(val),
                "project": f"{dom_id}-proj-main",
                "source": str(cal.relative_to(dom_dir)), "confirm_method": "文件",
            })
    return milestones, projects, calibers


def validate(dom_id: str, ms: list, ps: list, cs: list) -> tuple[int, int]:
    bad = total = 0
    for payload in ms:
        total += 1
        try:
            Milestone(**payload)
        except Exception:
            bad += 1
    for payload in ps:
        rec = {k: v for k, v in payload.items() if k != "source"}
        total += 1
        try:
            ProjectPilot(**rec)
        except Exception:
            bad += 1
    for payload in cs:
        rec = {k: v for k, v in payload.items() if k != "source"}
        total += 1
        try:
            Caliber(**rec)
        except Exception:
            bad += 1
    return bad, total


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--deep", default="", help="逗号分隔的深提炼域 id（里程碑上限 20）")
    args = ap.parse_args()
    deep_set = {x.strip() for x in args.deep.split(",") if x.strip()}
    reg = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    matrix = {"registry": reg.get("id"), "domains": [], "total": 0, "distilled": 0, "failed": 0,
              "deep_domains": sorted(deep_set)}
    # 聚合域（work-docs）由 kems-aggregate.py 维护子域投影，matrix 只读不写（防覆盖）
    AGGREGATE_DOMAINS = {"work-docs"}
    for entry in reg.get("manifests", []):
        dom_id = entry["id"]
        cap = MILESTONE_MAX_DEEP if dom_id in deep_set else MILESTONE_MAX
        dom_dir = resolve_domain_path(entry["path"])
        meta = probe(dom_dir)
        if dom_id in AGGREGATE_DOMAINS:
            inst_file = OUT_DIR / dom_id / "instances.yaml"
            if inst_file.exists():
                ad = yaml.safe_load(inst_file.read_text(encoding="utf-8"))
                total = sum(len(v) for v in ad.get("instances", {}).values())
                status = "OK"
                print(f"{dom_id}: {status} | instances={total}（子域聚合投影，matrix 只读）")
            else:
                total, status = 0, "OK"
                print(f"{dom_id}: {status} | instances=0（聚合投影未生成）")
            if status == "OK":
                matrix["distilled"] += total
            matrix["domains"].append({
                "id": dom_id, "path": str(dom_dir), "status": status,
                "distilled_instances": total, "bad": 0,
                "domain_meta": meta.get("domain"), "control_files": meta["control_files"],
                "extraction": meta.get("extraction"), "mode": "aggregate",
            })
            continue
        ms, ps, cs = distill(dom_id, dom_dir, cap)
        # 合并真实蒸馏实例（real-instances.yaml，独立文件防覆盖；matrix 写盘前并入 Milestone）
        real_f = OUT_DIR / dom_id / "real-instances.yaml"
        if real_f.exists():
            real = load_yaml_compat(real_f, "instances")
            if real.get("kind") == "milestone":
                seen = {m["id"] for m in ms}
                for r in real.get("instances", []):
                    rid = r.get("id", f"{dom_id}-real-x")
                    if rid in seen:
                        continue
                    d = r.get("date") or ""
                    rec = {"id": rid, "title": r.get("title", ""),
                           "severity": r.get("severity", "⚠️"), "owner": r.get("owner", ""),
                           "source": r.get("source", ""), "real": True}
                    if len(d) == 10:
                        rec["date"] = d[-5:]
                    elif re.match(r"^\d{2}-\d{2}$", d):
                        rec["date"] = d
                    else:
                        # 仅相对时间表达：无绝对日期，不参与 gate 时限判定
                        rec["date"] = "01-01"
                        rec["gateable"] = False
                    if r.get("relative"):
                        rec["note"] = f"相对时间表达：{r['relative']}"
                    ms.append(rec)
                    seen.add(rid)
        bad, total = validate(dom_id, ms, ps, cs)
        dom_out = OUT_DIR / dom_id
        dom_out.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "kems-pilot.instances.v1", "domain": dom_id,
            "provenance": "全域覆盖矩阵：SSOT registry 域发现 + 控制面只读探测 + 骨架蒸馏（通用 M2 校验）",
            "_domain_meta": meta.get("domain"),
            "instances": {"Milestone": ms, "ProjectPilot": ps, "Caliber": cs},
        }
        (dom_out / "instances.yaml").write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
        status = "OK" if bad == 0 else "FAIL"
        if bad == 0:
            matrix["distilled"] += total
        else:
            matrix["failed"] += 1
        matrix["domains"].append({
            "id": dom_id, "path": str(dom_dir), "status": status,
            "distilled_instances": total, "bad": bad,
            "domain_meta": meta.get("domain"), "control_files": meta["control_files"],
            "extraction": meta.get("extraction"),
        })
        print(f"{dom_id}: {status} | instances={total} | control={meta['control_files']}")
    matrix["total"] = len(matrix["domains"])
    (OUT_DIR / "domains-matrix.json").write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: matrix[k] for k in ("total", "distilled", "failed")}, ensure_ascii=False))
    return 0 if matrix["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
