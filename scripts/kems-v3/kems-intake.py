#!/usr/bin/env python3
"""kems-intake.py — 管道1 进料自动索引（kems-pilot 试点）。

归属：实现驻留执行面（kems-v3）；输入=任意待入库文件；输出=索引记录（含挂载候选/缺口）。

做三件事（对应用户场景1：新文件不自动索引、不挂时间线/事件线、关联资料易漏）：
  1) frontmatter 检查：title/date/status/owner 缺失 → 标记 intake 缺口；
  2) 本体挂载：文件名+内容命中本体键 → 候选实体 id（项目/环节/依据/事件），
     命中即建立"关联资料"候选，替代人工翻目录；
  3) 索引记录：写 ~/.kems-pilot/evidence/intake-<basename>.json（可追溯）。

负对照：--neg 传入无 frontmatter 文件 → 必须标记 failed（否则索引器形同虚设）。

用法：kems-intake.py <文件> [--domain <id>] [--neg]

  --domain 指定域（默认 work-weijian 试点域用内置词表，保证 P3/P4 验收口径不变）；
           其他域从 ~/.kems-pilot/domains/<id>/instances.yaml 派生挂载词表
           （本体数据即词表源——进料索引按本域本体挂载，不手抄关键词）。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

EVIDENCE_DIR = pathlib.Path.home() / ".kems-pilot/evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# 试点域内置本体挂载词表（对齐 kems-pilot M2：项目/环节/依据/事件）
MOUNT_KEYWORDS = {
    "ProjectPilot": ["三医诊疗数据归集", "数据归集", "归集模块", "家医健康", "FAMDOC", "LIS升级", "基层信息系统升级"],
    "WorkflowStage": ["经信局审核", "财政评审", "专家论证", "申请资金", "政府采购", "申报材料", "内部决策"],
    "Requirement": ["144号", "政策", "文号", "实施方案", "细则", "规划"],
    "PilotEvent": ["否决", "开标", "批示", "纪要", "会议", "动员"],
    "Deadline": ["20日", "月底", "截止", "报送", "硬时限", "评分"],
}

REQUIRED_FRONTMATTER = ["title", "date", "status", "owner"]

DOMAINS_DIR = pathlib.Path.home() / ".kems-pilot/domains"


def phrase_prefixes(text: str, min_n: int = 4, max_n: int = 10) -> list[str]:
    """确定性中文短语前缀候选：按分隔符切短语，每短语产出 4..max_n 字前缀。
    解决整句子串匹配过严的问题（如"养老服务体系建设调研报告"无法命中"养老服务体系建设"）。"""
    cands: list[str] = []
    for seg in re.split(r"[（(【\[、+，,。.\s|/：:;；]+", text or ""):
        seg = seg.strip("（()）[]【】、")
        if not seg or seg[0].isdigit():
            continue  # 排除日期/数字噪音（如 "2026"、"2026-07"）
        for n in range(min_n, min(len(seg), max_n) + 1):
            c = seg[:n]
            if c and c not in cands:
                cands.append(c)
    return cands


def vocab_from_instances(dom_id: str) -> dict[str, list[str]]:
    """非试点域：从域本体数据派生挂载词表（实例名/标题/要求/源文件名 + 短语前缀）。"""
    inst_file = DOMAINS_DIR / dom_id / "instances.yaml"
    vocab: dict[str, list[str]] = {}
    if not inst_file.exists():
        return vocab
    data = yaml.safe_load(inst_file.read_text(encoding="utf-8"))
    for kind, insts in (data.get("instances") or {}).items():
        # 真实蒸馏实例（业务词，real=True）优先，骨架实例随后
        ordered = sorted(insts, key=lambda i: 0 if i.get("real") else 1)
        words = []
        for i in ordered:
            for f in ("name", "title", "requirement_text", "full_name", "source"):
                v = i.get(f)
                if v and isinstance(v, str) and len(v) >= 2:
                    # 短语前缀优先（业务短语更易命中真实文本），完整片段随后
                    words.extend(phrase_prefixes(v))
                    words.append(v[:24])
        # 去重保序，限制词表规模（前 300 个候选，真实业务词优先入表）
        seen, dedup = set(), []
        for w in words:
            if w not in seen:
                seen.add(w)
                dedup.append(w)
        vocab[kind] = dedup[:300]
    return vocab


def check_frontmatter(text: str) -> list[str]:
    missing = []
    m = re.search(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return ["NO_FRONTMATTER_BLOCK"] + REQUIRED_FRONTMATTER
    fm = m.group(1)
    for key in REQUIRED_FRONTMATTER:
        if not re.search(rf"^{re.escape(key)}\s*:", fm, re.M):
            missing.append(key)
    return missing


def mount_candidates(name: str, text: str, vocab: dict[str, list[str]]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    hay = name + "\n" + text[:4000]
    for model, words in vocab.items():
        found = [w for w in words if w and w in hay]
        if found:
            hits[model] = found[:4]
    return hits


def register_index(domain: str, record: dict) -> None:
    """索引登记：按 basename 去重更新域索引面（负对照不登记，防污染）。"""
    import time as _t
    idx_path = DOMAINS_DIR / domain / "intake-index.json"
    idx: dict = {"schema": "kems-pilot.intake-index.v1", "domain": domain, "entries": {}}
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
        except Exception:
            idx = {"schema": "kems-pilot.intake-index.v1", "domain": domain, "entries": {}}
    idx["entries"][record["basename"]] = {
        "file": record["file"], "verdict": record["verdict"],
        "mount_candidates": record["mount_candidates"],
        "indexed_at": _t.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--neg"]
    neg = "--neg" in sys.argv
    domain = "work-weijian"
    if "--domain" in args:
        i = args.index("--domain")
        domain = args[i + 1]
        args = args[:i] + args[i + 2:]
    if not args:
        print("用法: kems-intake.py <文件> [--domain <id>] [--neg]")
        return 2
    target = pathlib.Path(args[0])
    text = target.read_text(encoding="utf-8", errors="replace")
    if neg:  # 负对照：注入缺 frontmatter 的文件形态
        text = "正文内容，无元数据头\n" + text.split("---", 2)[-1]

    vocab = MOUNT_KEYWORDS if domain == "work-weijian" else vocab_from_instances(domain)
    missing = check_frontmatter(text)
    hits = mount_candidates(target.name, text, vocab)
    verdict = "FAIL" if missing else "PASS"
    record = {
        "file": str(target),
        "basename": target.name,
        "domain": domain,
        "vocab_source": "内置词表(试点)" if domain == "work-weijian" else f"~/.kems-pilot/domains/{domain}/instances.yaml",
        "frontmatter_missing": missing,
        "mount_candidates": hits,
        "neg_control": neg,
        "verdict": verdict,
    }
    out = EVIDENCE_DIR / f"intake-{domain}-{target.stem}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    if not neg:  # 索引登记（负对照不登记）
        register_index(domain, record)
    print(json.dumps({"verdict": verdict, "domain": domain, "frontmatter_missing": missing,
                      "mount_candidates": hits}, ensure_ascii=False, indent=2))
    # 负对照必须 FAIL；正样本（有 frontmatter）必须 PASS
    ok = (verdict == "FAIL") if neg else (verdict == "PASS" and not missing)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
