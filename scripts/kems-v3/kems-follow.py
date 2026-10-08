#!/usr/bin/env python3
"""kems-follow.py — agent 可遵循性校验（R1-R7 确定性检查）。

规则声明=@公共/_control/KEMS-FOLLOWABILITY.yaml（权威文本见交付区规范文档）。
按 R1-R7 对 ~/.kems-pilot 证据面/数据面 + 交付区产物命名做静态校验，
输出 followability report（通过率 + 违反清单）。违反=机制信号，不允许解释跳过。

用法：kems-follow.py [--domains <id,id,...|all>]
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

H = pathlib.Path.home()
EVIDENCE = H / ".kems-pilot/evidence"
DOMAINS = H / ".kems-pilot/domains"
REPORTS = H / "Documents/@公共/_storage/05-交付区/06-KEMS知识工程"


def check() -> dict:
    results: list[dict] = []
    # R1 事实可溯：域 instances source 字段率
    r1 = {"rule": "R1", "ok": True, "detail": []}
    total_src = total = 0
    for f in DOMAINS.glob("*/instances.yaml"):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        for kind, rows in (data.get("instances") or {}).items():
            for r in rows:
                total += 1
                if r.get("source"):
                    total_src += 1
    rate = (total_src / total) if total else 1.0
    r1["ok"] = rate >= 0.9
    r1["detail"] = f"source 字段率 {rate:.1%}（{total_src}/{total}）"
    results.append(r1)

    # R2 先影子后真数据
    r2 = {"rule": "R2", "ok": True, "detail": []}
    sandbox = H / ".kems-pilot/卫健委-shadow/SANDBOX.md"
    baks = list(H.glob("Documents/@*/_control/*.bak-*")) + list(H.glob("Documents/@*/_control/*/*.bak-*"))
    r2["ok"] = sandbox.exists() and len(baks) > 0
    r2["detail"] = f"沙箱={sandbox.exists()} 备份数={len(baks)}"
    results.append(r2)

    # R3 数字可复算：evidence JSON 全部可解析
    r3 = {"rule": "R3", "ok": True, "detail": []}
    bad = []
    for f in EVIDENCE.glob("*.json"):
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            bad.append(f"{f.name}: {type(e).__name__}")
    r3["ok"] = not bad
    r3["detail"] = f"evidence json={len(list(EVIDENCE.glob('*.json')))} 无效={bad or '无'}"
    results.append(r3)

    # R4 冲突必暴露 + 裁决留痕（有冲突必有 decisions）
    r4 = {"rule": "R4", "ok": False, "detail": []}
    fusions = list(EVIDENCE.glob("fusion-*.json")) + list(EVIDENCE.glob("2026-10-08-p2-fusion.json"))
    exposed = [f for f in fusions if f.exists()]
    for f in exposed:
        d = json.loads(f.read_text(encoding="utf-8"))
        n_conf = d.get("summary", {}).get("conflicts_exposed", 0)
        n_dec = d.get("summary", {}).get("decisions", 0)
        neg = bool(d.get("summary", {}).get("neg_control") or d.get("neg_control"))
        if n_conf and not neg:
            # 真实冲突：必须逐条裁决留痕
            if n_dec >= n_conf:
                r4["ok"] = True
                r4["detail"].append(f"{f.name}: conflicts={n_conf} decisions={n_dec}（真实冲突，裁决留痕OK）")
            else:
                r4["detail"].append(f"{f.name}: conflicts={n_conf} decisions={n_dec}（真实冲突但裁决缺失！）")
        elif n_conf and neg:
            # 负对照冲突：验证暴露机制，无裁决语义，豁免
            r4["ok"] = True
            r4["detail"].append(f"{f.name}: conflicts={n_conf}（负对照暴露验证OK，无裁决语义）")
        else:
            r4["detail"].append(f"{f.name}: conflicts=0（单源无冲突）")
    if not exposed:
        r4["detail"].append("无 fusion evidence")
    results.append(r4)

    # R5 负对照必跑
    r5 = {"rule": "R5", "ok": False, "detail": []}
    for f in EVIDENCE.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(d, dict) and d.get("neg_control") is True:
            r5["ok"] = True
            r5["detail"].append(f.name)
    results.append(r5)

    # R6 产物契约（命名 YYYY-MM-DD 前缀抽查）
    r6 = {"rule": "R6", "ok": True, "detail": []}
    files = sorted(REPORTS.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
    for f in files:
        ok_name = bool(re.match(r"^\d{4}-\d{2}-\d{2}", f.name))
        r6["ok"] = r6["ok"] and ok_name
        r6["detail"].append(f"{f.name}: {'OK' if ok_name else '命名不合规'}")
    results.append(r6)

    # R7 不伪装全绿：报告含 待办/遗留/未完成 或 degraded 记录
    r7 = {"rule": "R7", "ok": False, "detail": []}
    recent = sorted(REPORTS.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
    for f in recent:
        txt = f.read_text(encoding="utf-8", errors="replace")
        if re.search(r"待办|遗留|未完成|degraded|待补|如实", txt):
            r7["ok"] = True
            r7["detail"].append(f.name)
    results.append(r7)

    # R8 授权边界（自动化审计面）：
    #   a) 子模块最近提交仅含预期路径（执行面 scripts/kems-v3、mof 声明/生成物）
    #   b) 域内零实现驻留：Documents 最近修改的可执行实现文件数 = 0
    #   c) 证据面非空
    r8 = {"rule": "R8", "ok": True, "detail": []}
    import subprocess
    allow_runtime = ["scripts/kems-v3", "docs"]
    allow_ecos = ["src/ecos/ssot/mof"]
    for repo, allow in (("runtime", allow_runtime), ("ecos", allow_ecos)):
        base = H / f"Workspace/projects/{repo}"
        r = subprocess.run(["git", "-C", str(base), "diff", "--name-only", "HEAD~1", "HEAD"],
                           capture_output=True, text=True)
        files = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
        out_of_scope = [f for f in files if not any(f.startswith(a) for a in allow)]
        if out_of_scope:
            r8["ok"] = False
        r8["detail"].append(f"{repo}: 提交文件 {len(files)} 越界={out_of_scope or '无'}")
    # b) 域内零实现驻留：活动域根目录（白名单）kems 足迹实现文件 = 0
    #    （跳过 _outputs 归档区与 Codex 区；白名单代替全盘 walk 提速）
    impl = []
    import os as _os
    doc_root = H / "Documents"
    active_roots = ["@公共", "@驾驶舱", "@工作文档", "@个人", "@家庭生活",
                    "@创意创作", "@OPC", "@学习进化"]
    for root_name in active_roots:
        base = doc_root / root_name
        if not base.exists():
            continue
        for root, dirs, files in _os.walk(base):
            dirs[:] = [d for d in dirs if d not in ("_outputs", "Codex", ".git", "_storage", "_knowledge")]
            for fname in files:
                if fname.lower().endswith((".py", ".sh", ".js")) and "kems" in fname.lower():
                    p = pathlib.Path(root) / fname
                    try:
                        age = (__import__("time").time() - p.stat().st_mtime) / 3600
                        if age < 48:
                            impl.append(str(p.relative_to(H)))
                    except OSError:
                        continue
    if impl:
        r8["ok"] = False
        r8["detail"].append(f"Documents 活动域 kems 实现文件(48h): {impl}")
    else:
        r8["detail"].append("Documents 活动域 kems 实现文件(48h): 无（零实现驻留）")
    # c) 证据面非空
    r8["detail"].append(f"evidence 文件数={len(list(EVIDENCE.glob('*.json')))}")
    results.append(r8)

    ok_n = sum(1 for r in results if r["ok"])
    report = {
        "schema": "kems-pilot.followability.v1", "asof": "2026-10-09",
        "pass_rate": f"{ok_n}/{len(results)}",
        "rules": results,
        "violations": [r["rule"] for r in results if not r["ok"]],
        "verdict": "PASS" if ok_n == len(results) else "VIOLATION",
    }
    (EVIDENCE / "followability-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    rep = check()
    for r in rep["rules"]:
        print(f"{r['rule']}: {'✅' if r['ok'] else '❌'} | {r['detail']}")
    print(f"VERDICT: {rep['verdict']}（{rep['pass_rate']}） violations={rep['violations']}")
    return 0 if rep["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
