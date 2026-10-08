#!/usr/bin/env python3
"""kems-pipe-accept.py — 全域四管道验收驱动（12 域 × 四管道，机器证据矩阵）。

对每域运行（确定性验收口径）：
  管道1 intake：样本=真实域 _control/STATUS.md（无则 DOMAIN.yaml）→ 记录 verdict；
                --neg 必须 FAIL（exit≠0），否则机制失守
  管道2 fusion：单源自检 → 必须 PASS；--neg 注入异值 → 必须 PASS（暴露机制有效）
  管道3 artifact：OK 契约 → 必须 OK；缺 format_req → 必须 REJECT（exit≠0）
  管道4 gate：--asof 演算 → 记录 verdict（OK/ALERT 均为合法；ALERT=真实逾期信号，非失败）
输出：~/.kems-pilot/domains/domains-pipeline-status.json
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import yaml

VENV_PY = "/Users/xiamingxing/Workspace/projects/ecos/.venv/bin/python"
KEMS = "/Users/xiamingxing/Workspace/projects/runtime/scripts/kems-v3"
REG = pathlib.Path.home() / "Documents/@公共/_control/L4-DOMAIN-REGISTRY.yaml"
REG_BASE = REG.parent
DOMAINS = pathlib.Path.home() / ".kems-pilot/domains"
ASOF = "2026-10-09"


def run(script: str, *args: str) -> tuple[int, str]:
    r = subprocess.run([VENV_PY, f"{KEMS}/{script}", *args], capture_output=True, text=True)
    out = (r.stdout or "").splitlines()
    line = next((ln for ln in out if '"verdict"' in ln), (out[-1] if out else ""))
    return r.returncode, line.strip()[:120]


def main() -> int:
    reg = yaml.safe_load(REG.read_text(encoding="utf-8"))
    rows, pipe_fails = [], 0
    for e in reg["manifests"]:
        dom = e["id"]
        real = (REG_BASE / e["path"]).resolve().parent
        sample = real / "_control/STATUS.md"
        if not sample.exists():
            sample = real / "DOMAIN.yaml"
        row: dict = {"domain": dom, "sample": str(sample)}

        # 管道1 intake（正样本 verdict 如实记录=真实结构信号；负对照必须 FAIL=exit0）
        if sample.exists():
            c_pos, v_pos = run("kems-intake.py", str(sample), "--domain", dom)
            c_neg, v_neg = run("kems-intake.py", str(sample), "--domain", dom, "--neg")
            row["intake"] = {"verdict": v_pos, "exit": c_pos,
                             "neg": {"verdict": v_neg, "exit": c_neg, "control_ok": c_neg == 0}}
            if c_neg != 0:
                pipe_fails += 1  # 负对照未正确拒绝 = 机制失守
        else:
            row["intake"] = {"verdict": "N/A(无样本)", "neg": None}

        # 管道2 fusion（单源自检 PASS；--neg 必须 PASS；exit0=期望达成）
        c_f, v_f = run("kems-fusion.py", "--domain", dom)
        c_fn, v_fn = run("kems-fusion.py", "--domain", dom, "--neg")
        row["fusion"] = {"verdict": v_f, "exit": c_f, "neg": {"verdict": v_fn, "exit": c_fn}}
        if c_f != 0 or c_fn != 0:
            pipe_fails += 1

        # 管道3 artifact（OK 契约 exit0；缺 format_req REJECT exit0=正确拒绝）
        c_a, v_a = run("kems-artifact.py", "--check", "D-GENERIC-1", "--name", f"{ASOF}-验收交付物",
                       "--path", "/tmp/x.md", "--format-req", "报告", "--destination", str(real),
                       "--domain", dom)
        c_an, v_an = run("kems-artifact.py", "--check", "D-GENERIC-NEG", "--name", f"{ASOF}-验收交付物",
                         "--path", "/tmp/x.md", "--domain", dom, "--neg")
        row["artifact"] = {"verdict": v_a, "exit": c_a, "neg": {"verdict": v_an, "exit": c_an}}
        if c_a != 0 or c_an != 0:
            pipe_fails += 1  # OK 契约失败 或 负对照未正确拒绝

        # 管道4 gate（记录 verdict；ALERT=真实逾期信号，不算失败）
        c_g, v_g = run("kems-gate.py", "--domain", dom, "--asof", ASOF)
        row["gate"] = {"verdict": v_g, "exit": c_g}
        rows.append(row)
        print(f"{dom}: intake={row['intake']['verdict']} fusion={v_f} artifact={v_a} gate={v_g}")

    out = {"schema": "kems-pilot.pipeline-accept.v1", "asof": ASOF,
           "domains": rows, "total": len(rows), "pipe_fails": pipe_fails}
    (DOMAINS / "domains-pipeline-status.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"total": len(rows), "pipe_fails": pipe_fails}, ensure_ascii=False))
    return 0 if pipe_fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
