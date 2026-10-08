#!/usr/bin/env python3
"""kems-status.py — 读面：四管道运行状态聚合（intake_status / fusion_queue 等）。

归属：实现驻留执行面（kems-v3）。供 agent 读面（MCP/CLI）一次性查看四管道最新状态：
进料索引记录、融合队列与冲突数、产物契约核验、门禁倒计时/逾期/阻塞。
数据源=~/.kems-pilot/evidence/*.json（每次管道运行的机器证据）。

用法：kems-status.py [--raw]
"""
from __future__ import annotations

import json
import pathlib
import sys

EVIDENCE = pathlib.Path.home() / ".kems-pilot/evidence"


def latest_by_prefix(prefix: str, skip: tuple[str, ...] = ()) -> dict | None:
    cands = [p for p in EVIDENCE.glob(f"{prefix}*") if p.is_file() and p.suffix == ".json"
             and p.name not in skip]
    if not cands:
        return None
    newest = max(cands, key=lambda p: p.stat().st_mtime)
    return json.loads(newest.read_text(encoding="utf-8"))


def main() -> int:
    intake = latest_by_prefix("intake-", skip=("2026-10-08-p1-validation.json",))
    fusion = latest_by_prefix("2026-10-08-p2-fusion")
    artifact = latest_by_prefix("artifact-")
    gate = latest_by_prefix("gate-")

    status = {
        "schema": "kems-pilot.pipeline-status.v1",
        "asof": "2026-10-08",
        "pipes": {
            "intake": {
                "last_file": intake.get("basename") if intake else None,
                "verdict": intake.get("verdict") if intake else None,
                "mount_candidates": intake.get("mount_candidates", {}) if intake else None,
                "frontmatter_missing": intake.get("frontmatter_missing", []) if intake else None,
            } if intake else None,
            "fusion": {
                "sources": fusion.get("summary", {}).get("sources", []) if fusion else None,
                "conflicts_exposed": fusion.get("summary", {}).get("conflicts_exposed", 0) if fusion else 0,
                "decisions": fusion.get("summary", {}).get("decisions", 0) if fusion else 0,
                "verdict": fusion.get("summary", {}).get("verdict") if fusion else None,
            } if fusion else None,
            "artifact": {
                "last_deliverable": artifact.get("deliverable") if artifact else None,
                "verdict": artifact.get("verdict") if artifact else None,
                "violations": artifact.get("violations", []) if artifact else None,
            } if artifact else None,
            "gate": {
                "overdue": gate.get("overdue", []) if gate else None,
                "due_soon": gate.get("due_soon", []) if gate else None,
                "blocked_milestones": gate.get("blocked_milestones", []) if gate else None,
                "violations": gate.get("gate_violations", []) if gate else None,
                "verdict": gate.get("verdict") if gate else None,
            } if gate else None,
        },
    }
    out = EVIDENCE / "pipeline-status.json"
    out.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    if "--raw" in sys.argv:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        for name, p in status["pipes"].items():
            v = p.get("verdict") if p else "N/A"
            extra = ""
            if name == "fusion" and p:
                extra = f" (conflicts={p['conflicts_exposed']}, decisions={p['decisions']})"
            if name == "gate" and p:
                extra = f" (overdue={p['overdue']}, due_soon={p['due_soon']}, blocks={len(p['blocked_milestones'])})"
            print(f"{name}: {v}{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
