#!/usr/bin/env python3
"""kems-e2e.py — 事件闭环编排：一条命令串四管道（intake→fusion→artifact→gate）。

背景：四管道独立可用，但"一次事件闭环"需要手工连跑 4 条命令。
本工具把工作流固化为一条命令（程序为核心，agent 只需触发与读结论）。

用法：
  kems-e2e.py --domain work-weijian --asof 2026-10-20 --sample <文件>
  kems-e2e.py --domain creative --asof 2026-10-09 --sample <域内文件>   # 跨域同构
参数：
  --domain 域 id（默认 work-weijian）；--asof 门禁演算日；--sample 进料样本文件
输出：
  ~/.kems-pilot/evidence/e2e-<domain>-<asof>.json（四管道聚合证据）+ 终端摘要
验收口径：四管道各自正/负对照逻辑不变；e2e 本身聚合展示（不改变管道判定）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

VENV_PY = "/Users/xiamingxing/Workspace/projects/ecos/.venv/bin/python"
KEMS = pathlib.Path(__file__).resolve().parent
EVIDENCE = pathlib.Path.home() / ".kems-pilot/evidence"


def run(name: str, *args: str) -> dict:
    r = subprocess.run([VENV_PY, str(KEMS / name), *args], capture_output=True, text=True)
    return {"cmd": f"{name} {' '.join(args)}", "exit": r.returncode,
            "stdout": (r.stdout or "").strip(), "out_tail": (r.stdout or "").strip()[-400:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="work-weijian")
    ap.add_argument("--asof", default="2026-10-09")
    ap.add_argument("--sample", required=True, help="进料样本文件（事件侧新增材料）")
    ap.add_argument("--deliverable", default="D-E2E-1")
    ap.add_argument("--dest", default="")
    args = ap.parse_args()

    steps = {
        "1_intake": run("kems-intake.py", args.sample, "--domain", args.domain),
        "2_fusion": run("kems-fusion.py", "--domain", args.domain),
        "3_artifact": run("kems-artifact.py", "--check", args.deliverable,
                          "--name", f"{args.asof}-e2e交付物", "--path", args.sample,
                          "--format-req", "事件闭环产物", "--destination", args.dest or str(pathlib.Path(args.sample).parent),
                          "--domain", args.domain),
        "4_gate": run("kems-gate.py", "--domain", args.domain, "--asof", args.asof),
    }
    report = {"schema": "kems-pilot.e2e.v1", "domain": args.domain, "asof": args.asof,
              "steps": steps,
              "all_ok": all(
                  s["exit"] == 0 or (name == "4_gate" and '"verdict": "ALERT"' in s["stdout"])
                  for name, s in steps.items())}
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / f"e2e-{args.domain}-{args.asof}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, s in steps.items():
        gate_alert = (k == "4_gate" and '"verdict": "ALERT"' in s["stdout"])
        verdict = "OK" if (s["exit"] == 0 or gate_alert) else "❌"
        print(f"{k}: {verdict} (exit={s['exit']}{', ALERT信号已捕获' if gate_alert else ''})")
    print(f"E2E_ALL_OK: {report['all_ok']} | evidence={out.name}")
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
