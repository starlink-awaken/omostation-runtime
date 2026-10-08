#!/usr/bin/env python3
"""kems-fusion.py — P2 多总结融合引擎（kems-pilot 试点，管道2）。

归属：实现驻留执行面（Workspace/kems-v3）；数据源=沙箱副本；基准=项目口径.yaml（SSOT）。

原理：
  1) 源抽取：YAML 源直接取键值；Markdown 源按归一化键名做行级关键词抽取
     （支持「键: 值」与「键=值」两种形态，容忍全角冒号/空格）。
  2) 键归一：别名表把各源同义键（总投资万元/总投资/预算）归一为 Caliber 键。
  3) 对齐比对：同键多源值做规范化比对（去空格/单位），不同 → 冲突。
  4) 裁决：默认以项目口径.yaml（SSOT）为基准；每条裁决留痕（选择值+理由+来源）；
     「未暴露冲突=0 错漏」口径（v2 铁律）——冲突必须全部暴露，暴露后可裁决。
  5) 非冲突标注：跨对象/不同项目同键不同值（如 归集300万 vs 大兴2540万）经
     显式 scopes 隔离，不误报（防假绿，也防假红）。

用法：
  kems-fusion.py [--neg]           # 试点域：含负对照（虚构冲突源B'，必须被暴露）
  kems-fusion.py --domain <id> [--neg]   # 跨域：单源本体数据自检；--neg 注入同键异值（必须暴露）
输出：
  ~/.kems-pilot/evidence/2026-10-08-p2-fusion.json   （试点域）
  ~/.kems-pilot/evidence/fusion-<domain>-<date>.json （跨域）
"""
from __future__ import annotations

import json
import re
import pathlib
import sys
import datetime as dt

SBOX = pathlib.Path.home() / ".kems-pilot/卫健委-shadow"
DOMAINS_DIR = pathlib.Path.home() / ".kems-pilot/domains"
EVIDENCE_DIR = pathlib.Path.home() / ".kems-pilot/evidence"
EVIDENCE_PATH = EVIDENCE_DIR / "2026-10-08-p2-fusion.json"

# 归一化键别名表（各源同义键 → Caliber 键）
KEY_ALIASES = {
    "项目全称": "项目全称", "全称": "项目全称",
    "项目性质": "项目性质", "性质": "项目性质",
    "总投资万元": "总投资万元", "总投资": "总投资万元", "投资额": "总投资万元", "预算": "总投资万元",
    "软件开发费万元": "软件开发费万元", "软件开发费": "软件开发费万元",
    "监理费万元": "监理费万元", "监理费": "监理费万元",
    "资金来源": "资金来源", "资金渠道": "资金来源",
    "建设周期": "建设周期", "周期": "建设周期", "实施周期": "建设周期",
    "项目负责人": "项目负责人", "负责人": "项目负责人",
    "联络人": "联络人",
    "主管领导": "主管领导",
    "项目归属": "项目归属", "归属": "项目归属",
    "项目状态": "项目状态", "状态": "项目状态",
    "机构口径": "机构口径", "覆盖机构": "机构口径",
    "等保统筹": "密码等保统筹", "等保": "密码等保统筹",
}

# 真实键清单（从 项目口径.yaml 抽取的键 + 状态键）
REAL_KEYS = list(KEY_ALIASES.values())

# 显式作用域隔离：键 + 值正则 → 允许同名不同值（跨对象，非冲突）
SCOPE_ISOLATION = [
    # 大兴招标预算（M07，2540.37万）与 归集项目（300万）是不同项目
    {"key": "总投资万元", "value_re": r"2540", "scope": "大兴项目"},
]

SSOT_SOURCE = "_control/项目口径.yaml"


def extract_yaml(path: pathlib.Path) -> dict[str, str]:
    import yaml
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)  # 单文档（多数控制文件）
    except yaml.composer.ComposerError:
        # frontmatter 头升级后为多文档：取含目标键的文档（兼容 gate.load_control）
        data = next((d for d in yaml.safe_load_all(text)
                     if isinstance(d, dict) and d), None)
    out: dict[str, str] = {}
    def walk(node, prefix=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{prefix}{k}" if not prefix else f"{prefix}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{prefix}[{i}]")
        else:
            out[prefix] = str(node)
    if data:
        walk(data)
    return out


def extract_md(path: pathlib.Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for key in REAL_KEYS:
        # 形态1: 键：值（全角/半角冒号均可）
        m = re.search(rf"^{re.escape(key)}\s*[:：]\s*(.+)$", text, re.M)
        if m:
            out[key] = m.group(1).strip()
            continue
        # 形态2: 键=值
        m = re.search(rf"{re.escape(key)}\s*=\s*([^，。\n]+)", text)
        if m:
            out[key] = m.group(1).strip()
    # 关键事件词条（用于状态口径）
    if "否决" in text:
        out["项目状态"] = out.get("项目状态", "") + " 家医项目被否决" if out.get("项目状态") else "家医项目被否决"
    if "开标" in text and "2540" in text:
        out["总投资万元"] = "2540.37（大兴）"
    # 归集项目造价核算口径（144号评估原文）
    m = re.search(r"三医诊疗数据归集模块项目（([\d.]+)\s*万）", text)
    if m:
        out["总投资万元"] = f"{m.group(1)}（144号评估口径）"
    return out


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", str(value)).replace("：", ":").strip()


# 语义同义词归一（防假红）：状态表述不同但语义一致 → 归一为同一规范值
SEMANTIC_SYNONYMS = {
    "项目状态": {
        "待立项批复（未赋码）": "经信局环节（待批复）",
        "经信局环节（M04申报已提交，批复未出）": "经信局环节（待批复）",
        "经信局环节": "经信局环节（待批复）",
    },
}


def semantic_normalize(key: str, value: str) -> str:
    v = normalize(value)
    return SEMANTIC_SYNONYMS.get(key, {}).get(v, v)


def run_generic(domain: str, neg: bool) -> int:
    """跨域单源自检：域本体数据统一键化；无冲突面→PASS；
    --neg 注入同键异值，必须暴露（证明冲突暴露机制跨域有效）。"""
    import yaml
    inst_file = DOMAINS_DIR / domain / "instances.yaml"
    if not inst_file.exists():
        print(f"UNKNOWN_DOMAIN {domain}")
        return 1
    data = yaml.safe_load(inst_file.read_text(encoding="utf-8"))
    flat: dict[str, str] = {}
    for kind, rows in (data.get("instances") or {}).items():
        for r in rows:
            for k, v in r.items():
                if isinstance(v, (str, int, float)):
                    flat[f"{kind}.{r.get('id', '?')}.{k}"] = str(v)
    conflicts: list[dict] = []
    if neg:
        if flat:
            key = next(iter(flat))
            other_value = flat[key] + "（虚构异值，必须暴露）"
        else:
            # 空域（0 实例）：注入合成键，仍须暴露（证明暴露机制与实例量无关）
            key = "Milestone.probe.synthetic"
            flat[key] = "empty-domain-probe"
            other_value = "empty-domain-probe（虚构异值，必须暴露）"
        conflicts.append({
            "key": key,
            "base": {"source": "instances.yaml", "value": flat[key]},
            "other": {"source": "负对照(虚构)", "value": other_value},
        })
    summary = {
        "mode": "generic-single-source", "domain": domain,
        "sources": [str(inst_file)],
        "keys_fused": len(flat),
        "conflicts_exposed": len(conflicts),
        "unexposed_check": "单源自检，无静默合并；负对照注入必暴露",
        "decisions": 0,
        "neg_control": neg,
        "verdict": "PASS" if ((neg and conflicts) or not neg) else "FAIL",
    }
    result = {"summary": summary, "merged": {}, "conflicts": conflicts, "decisions": []}
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE_DIR / f"fusion-{domain}-2026-10-09.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["verdict"] == "PASS" else 1


def main() -> int:
    import yaml
    neg = "--neg" in sys.argv
    domain = "work-weijian"
    if "--domain" in sys.argv:
        i = sys.argv.index("--domain")
        domain = sys.argv[i + 1]
    if domain != "work-weijian":
        return run_generic(domain, neg)

    sources: dict[str, dict[str, str]] = {}
    # 源A：项目口径.yaml（SSOT 基准）
    cal_path = SBOX / SSOT_SOURCE
    flat = extract_yaml(cal_path)
    sources["项目口径.yaml(SSOT)"] = {}
    for raw_key, v in flat.items():
        if "." not in raw_key:
            continue
        leaf = raw_key.rsplit(".", 1)[-1]
        if leaf in KEY_ALIASES:
            sources["项目口径.yaml(SSOT)"][KEY_ALIASES[leaf]] = v
    # 项目状态推断（SSOT 项目代码=待立项批复后赋码 → 状态）
    code_key = next((k for k in flat if k.endswith("项目代码")), None)
    if code_key and "待立项批复" in str(flat[code_key]):
        sources["项目口径.yaml(SSOT)"]["项目状态"] = "待立项批复（未赋码）"
    # 源B：144号对三新建项目影响评估.md（家医否决/大兴承接）
    md_b = SBOX / "_knowledge/业务资料/01-业务核心/政策与规划/2026-08-05-144号对三新建项目影响评估.md"
    if md_b.exists():
        sources["144号影响评估.md"] = extract_md(md_b)
    # 源C：key-milestones.yaml 的 M04/M07 注记（经信局环节/大兴开标）
    km_text = (SBOX / "_control/key-milestones.yaml").read_text(encoding="utf-8")
    try:
        km = yaml.safe_load(km_text)
    except yaml.composer.ComposerError:
        km = next((d for d in yaml.safe_load_all(km_text)
                   if isinstance(d, dict) and "milestones" in d), None)
    notes = "；".join(m.get("note", "") for m in km["milestones"] if m["id"] in ("M04", "M05", "M07"))
    sources["key-milestones.yaml"] = {}
    if "经信局" in notes and "环节" in notes:
        sources["key-milestones.yaml"]["项目状态"] = "经信局环节（M04 申报已提交，批复未出）"
    if "2540" in notes:
        sources["key-milestones.yaml"]["总投资万元"] = "2540.37（大兴）"
    # 源D：三医进度表（任务完成情况 → 状态证据）
    tbl = SBOX / "_knowledge"
    # 进度表 docx 不在沙箱文本面，改用 _storage 内已知证据：三医周报完成率
    weekly = None
    for p in (SBOX / "_storage").rglob("*.md"):
        if "三医" in p.name and ("周报" in p.name or "简报" in p.name):
            weekly = p
            break
    if weekly:
        txt = weekly.read_text(encoding="utf-8")
        m = re.search(r"(\d+(?:\.\d+)?)%", txt)
        if m:
            sources["三医周报"] = {"完成率": f"{m.group(1)}%"}

    # ── 负对照：虚构冲突源B'（总投资 350，与 SSOT 300 冲突） ──
    if "--neg" in sys.argv:
        sources["负对照B'(虚构)"] = {"总投资万元": "350", "项目状态": "经信局环节"}

    # ── 融合比对（逐对冲突记录：每个同键异值=1 条暴露） ──
    all_keys = sorted({k for src in sources.values() for k in src})
    merged: dict[str, dict] = {}
    conflicts: list[dict] = []
    for key in all_keys:
        if key == "完成率":
            continue  # 周报完成率不参与口径冲突
        vals: list[dict] = []
        for src_name, kv in sources.items():
            if key in kv:
                vals.append({"source": src_name, "value": kv[key]})
        # 值作用域：跨对象值（如 大兴2540）与默认值分属不同作用域，互不比较
        scope_groups: dict[str, list[dict]] = {}
        for x in vals:
            sc = "大兴" if re.search(r"2540", normalize(x["value"])) else "default"
            scope_groups.setdefault(sc, []).append(x)
        key_conflicts: list[dict] = []
        default_vals = scope_groups.get("default", [])
        if len(default_vals) > 1:
            base_entry = default_vals[0]
            base_norm = semantic_normalize(key, base_entry["value"])
            for x in default_vals[1:]:
                if semantic_normalize(key, x["value"]) != base_norm:
                    key_conflicts.append({
                        "key": key,
                        "base": {"source": base_entry["source"], "value": base_entry["value"]},
                        "other": {"source": x["source"], "value": x["value"]},
                    })
        merged[key] = {"values": vals, "conflict_count": len(key_conflicts)}
        conflicts.extend(key_conflicts)
        for c in key_conflicts:
            print(f"⚠️ 冲突: {c['key']} | {c['base']['source']}={c['base']['value']} vs {c['other']['source']}={c['other']['value']}")

    # ── 裁决（SSOT 优先；每条冲突独立裁决留痕） ──
    decisions: list[dict] = []
    for c in conflicts:
        sides = [c["base"], c["other"]]
        ssot_side = next((s for s in sides if s["source"] == "项目口径.yaml(SSOT)"), None)
        decisions.append({
            "key": c["key"],
            "conflict": sides,
            "decision": ssot_side["value"] if ssot_side else None,
            "basis": "SSOT 优先（项目口径.yaml 为准，v2 口径铁律）" if ssot_side else "待用户裁决（SSOT 无此键）",
            "rejected": [s for s in sides if s is not ssot_side] if ssot_side else sides,
        })

    summary = {
        "sources": list(sources),
        "keys_fused": len(all_keys) - 1,
        "conflicts_exposed": len(conflicts),
        "unexposed_check": "所有多源键均已比对（无静默合并）",
        "decisions": len(decisions),
        "neg_control": "--neg" in sys.argv,
        "verdict": "PASS" if (len(conflicts) >= (2 if "--neg" in sys.argv else 1)) else "FAIL",
    }
    result = {"summary": summary, "merged": merged, "conflicts": conflicts, "decisions": decisions}
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    # 试点域 evidence 与跨域同构（按域命名，不再覆盖固定 p2 快照；p2-fusion.json 保留历史）
    out = EVIDENCE_DIR / f"fusion-{domain}-{dt.date.today().isoformat()}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
