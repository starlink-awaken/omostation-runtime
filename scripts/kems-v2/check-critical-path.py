#!/usr/bin/env python3
"""check-critical-path.py — 关键路径检查（v2，SSOT = key-milestones.yaml）

读取 _control/key-milestones.yaml 的 milestones 列表，检查：
  1. 关键里程碑节点状态（✅完成 / 🟡逾期 / 🟡即将到期 / ⛔阻塞 / ⚠️存疑 / ❌失败）
  2. 周期性任务（每月20日月报、每双周双周报）到期/遗漏提示

设计说明（2026-09-17 G13/N6 闭环）：
  - 旧版读取 _control/项目口径.yaml 的「关键节点」键（裸日期列表），
    与 key-milestones.yaml 的 milestones 列表构成双写。
  - 现以 key-milestones.yaml 为唯一 SSOT（字段更完整：id/date/title/
    severity/owner/gap_ids/req_files/note）。项目口径.yaml 已移除该键。
  - severity 字段实为状态语义，前缀 emoji 决定分类：
      ✅ 已完成 → 正常
      🟡 + "即将" → 即将到期（upcoming）
      🟡（逾期） → 逾期（overdue），计入退出码
      ⛔ 阻塞 → 前置未达成，不计逾期
      ⚠️ 存疑 → 待人工确认，不计逾期
      ❌ 失败 → 逾期/失败，计入退出码

用法：
  python3 check-critical-path.py --root <域根>
退出码：0=无逾期（无🟡逾期/❌），1=存在逾期项。
"""
import argparse
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml


def resolve_root(raw):
    p = Path(raw).expanduser().resolve()
    if not p.is_dir():
        sys.exit(f"❌ 域根不存在: {p}")
    return p


def main():
    ap = argparse.ArgumentParser(description="关键路径节点与周期性任务检查")
    ap.add_argument("--root", required=True, help="域根绝对路径")
    args = ap.parse_args()
    domain = resolve_root(args.root)
    today = date.today()
    current_year = today.year

    print("=" * 60)
    print("🎯 关键路径检查")
    print(f"   域: {domain}")
    print(f"   今天: {today}")
    print("=" * 60)

    overdue = []
    upcoming = []
    normal = []

    # ── 1. 关键里程碑（SSOT: key-milestones.yaml）──
    ms_file = domain / "_control" / "key-milestones.yaml"
    if not ms_file.is_file():
        print(f"\n[1] ❌ 未找到关键路径 SSOT: {ms_file}")
        sys.exit(1)

    data = yaml.safe_load(ms_file.read_text(encoding="utf-8")) or {}
    milestones = data.get("milestones", []) or []
    ver = data.get("version", "?")
    print(f"\n[1] 项目关键里程碑（SSOT: key-milestones.yaml v{ver}，共 {len(milestones)} 个）")

    for ms in milestones:
        mid = ms.get("id", "?")
        raw_date = str(ms.get("date", ""))
        title = ms.get("title", "")
        severity = str(ms.get("severity", ""))
        owner = ms.get("owner", "")

        # 解析 MM-DD → YYYY-MM-DD（用当前年份）
        try:
            dt = datetime.strptime(f"{current_year}-{raw_date}", "%Y-%m-%d").date()
        except (ValueError, TypeError):
            print(f"   ⚠️ {mid}: 日期不可解析 ({raw_date}) — {title}")
            continue

        days = (dt - today).days
        owner_str = f" [{owner}]" if owner else ""

        # 根据 severity 前缀判断状态分类
        if "⛔" in severity:
            # 阻塞：前置未达成，不计逾期
            print(f"   ⛔ {mid} {title}: {dt}{owner_str}（阻塞 — 前置未达成，非逾期）")
            normal.append((mid, dt, days, "阻塞"))
        elif "🟡" in severity and "即将" in severity:
            # 即将到期
            print(f"   🟡 {mid} {title}: {dt}{owner_str}（{days} 天后到期）")
            upcoming.append((mid, dt, days))
        elif "🟡" in severity:
            # 逾期
            print(f"   🟡 {mid} {title}: {dt}{owner_str}（已逾期 {-days} 天）")
            overdue.append((mid, dt, days))
        elif "⚠️" in severity:
            # 存疑：待人工确认，不计逾期
            print(f"   ⚠️ {mid} {title}: {dt}{owner_str}（{severity}）")
            normal.append((mid, dt, days, "存疑"))
        elif "✅" in severity:
            print(f"   ✅ {mid} {title}: {dt}{owner_str}（已完成）")
            normal.append((mid, dt, days, "已完成"))
        elif "❌" in severity:
            print(f"   ❌ {mid} {title}: {dt}{owner_str}（已逾期 {-days} 天）")
            overdue.append((mid, dt, days))
        else:
            # 无明确 severity 标记，按日期兜底计算
            if days < 0:
                print(f"   ❌ {mid} {title}: {dt}{owner_str}（已逾期 {-days} 天，未标状态）")
                overdue.append((mid, dt, days))
            elif 0 <= days <= 7:
                print(f"   ⚠️ {mid} {title}: {dt}{owner_str}（{days} 天后到期）")
                upcoming.append((mid, dt, days))
            else:
                print(f"   ✅ {mid} {title}: {dt}{owner_str}（{days} 天后）")
                normal.append((mid, dt, days, "正常"))

    # ── 2. 周期性任务 ──
    print("\n[2] 周期性任务")
    timeline = domain / "_control" / "TIMELINE.md"
    timeline_text = timeline.read_text(encoding="utf-8", errors="replace") if timeline.is_file() else ""

    # 月报：每月20日
    this_month_20 = date(today.year, today.month, 20)
    if today.day <= 20:
        next_report = this_month_20
    else:
        if today.month == 12:
            next_report = date(today.year + 1, 1, 20)
        else:
            next_report = date(today.year, today.month + 1, 20)
    days_to_report = (next_report - today).days
    print(f"   · 月报（每月20日）: 下次 {next_report}（{days_to_report} 天后）")
    if days_to_report <= 3:
        upcoming.append(("月报(周期)", next_report, days_to_report))
        print("     ⚠️ 3天内到期")

    # 双周报：每双周一次，从 TIMELINE 中查找
    shuangzhou = [m for m in re.findall(r"(\d{2}-\d{2}).*?双周", timeline_text)]
    print(f"   · 双周报: TIMELINE 中近 {len(shuangzhou)} 处提及")

    # ── 汇总 ──
    print("\n" + "=" * 60)
    print(f"📊 逾期项: {len(overdue)}")
    if overdue:
        for name, d, days in overdue:
            print(f"   ❌ {name} {d}（{-days}天）")
    print(f"📊 即将到期(7天内): {len(upcoming)}")
    if upcoming:
        for item in upcoming:
            name, d, days = item[0], item[1], item[2]
            print(f"   ⚠️ {name} {d}（{days}天）")
    print(f"📊 正常/已完成/阻塞/存疑: {len(normal)}")
    print("=" * 60)
    sys.exit(1 if overdue else 0)


if __name__ == "__main__":
    main()
