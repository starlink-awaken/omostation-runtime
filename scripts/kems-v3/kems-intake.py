#!/usr/bin/env python3
"""kems-intake.py — 管道1 进料自动索引（kems-pilot 试点）。

归属：实现驻留执行面（kems-v3）；输入=任意待入库文件；输出=索引记录（含挂载候选/缺口）。

做三件事（对应用户场景1：新文件不自动索引、不挂时间线/事件线、关联资料易漏）：
  1) frontmatter 检查：title/date/status/owner 缺失 → 标记 intake 缺口；
  2) 本体挂载：文件名+内容命中本体键 → 候选实体 id（项目/环节/依据/事件），
     命中即建立"关联资料"候选，替代人工翻目录；
  3) 索引记录：写 ~/.kems-pilot/evidence/intake-<basename>.json（可追溯）。

负对照：--neg 传入无 frontmatter 文件 → 必须标记 failed（否则索引器形同虚设）。

用法：kems-intake.py <文件> [--neg]
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

EVIDENCE_DIR = pathlib.Path.home() / ".kems-pilot/evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# 本体挂载词表（对齐 kems-pilot M2：项目/环节/依据/事件）
MOUNT_KEYWORDS = {
    "ProjectPilot": ["三医诊疗数据归集", "数据归集", "归集模块", "家医健康", "FAMDOC", "LIS升级", "基层信息系统升级"],
    "WorkflowStage": ["经信局审核", "财政评审", "专家论证", "申请资金", "政府采购", "申报材料", "内部决策"],
    "Requirement": ["144号", "政策", "文号", "实施方案", "细则", "规划"],
    "PilotEvent": ["否决", "开标", "批示", "纪要", "会议", "动员"],
    "Deadline": ["20日", "月底", "截止", "报送", "硬时限", "评分"],
}

REQUIRED_FRONTMATTER = ["title", "date", "status", "owner"]


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


def mount_candidates(name: str, text: str) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    hay = name + "\n" + text[:4000]
    for model, words in MOUNT_KEYWORDS.items():
        found = [w for w in words if w in hay]
        if found:
            hits[model] = found[:4]
    return hits


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: kems-intake.py <文件> [--neg]")
        return 2
    target = pathlib.Path(sys.argv[1])
    text = target.read_text(encoding="utf-8", errors="replace")
    neg = "--neg" in sys.argv
    if neg:  # 负对照：注入缺 frontmatter 的文件形态
        text = "正文内容，无元数据头\n" + text.split("---", 2)[-1]

    missing = check_frontmatter(text)
    hits = mount_candidates(target.name, text)
    verdict = "FAIL" if missing else "PASS"
    record = {
        "file": str(target),
        "basename": target.name,
        "frontmatter_missing": missing,
        "mount_candidates": hits,
        "neg_control": neg,
        "verdict": verdict,
    }
    out = EVIDENCE_DIR / f"intake-{target.stem}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "frontmatter_missing": missing,
                      "mount_candidates": hits}, ensure_ascii=False, indent=2))
    # 负对照必须 FAIL；正样本（有 frontmatter）必须 PASS
    ok = (verdict == "FAIL") if neg else (verdict == "PASS" and not missing)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
