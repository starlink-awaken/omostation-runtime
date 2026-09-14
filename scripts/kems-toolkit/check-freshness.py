#!/usr/bin/env python3
"""检查所有 Markdown 文件的 last-reviewed 字段，报告过期文件。"""
import os
import re
import sys
from datetime import date, timedelta

WARN_DAYS = 7
CRITICAL_DAYS = 14
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def check_freshness():
    fresh, warn, critical, no_date = [], [], [], []
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs if not d.startswith('.')] 
        for fname in files:
            if not fname.endswith('.md'):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath) as f:
                content = f.read()
            m = re.search(r'last-reviewed:\s*(\d{4}-\d{2}-\d{2})', content)
            if not m:
                no_date.append(fpath.replace(BASE+'/',''))
                continue
            fdate = date.fromisoformat(m.group(1))
            age = (date.today() - fdate).days
            rel = fpath.replace(BASE+'/','')
            if age > CRITICAL_DAYS:
                critical.append((rel, age))
            elif age > WARN_DAYS:
                warn.append((rel, age))
            else:
                fresh.append(rel)

    total = len(fresh) + len(warn) + len(critical) + len(no_date)
    rate = round(len(warn)+len(critical)+len(no_date) / max(total,1) * 100)
    print("=== KEMS Freshness Check ===")
    print(f"Total: {total} | Fresh: {len(fresh)} | Warn: {len(warn)} | Critical: {len(critical)} | NoDate: {len(no_date)}")
    print(f"Stale Rate: {rate}% {'⚠️ >10%' if rate > 10 else '✅'}")
    if warn:
        print("\n⚠️  Warning (>7 days):")
        for p, a in warn: print(f"  {p} ({a}d)")
    if critical:
        print("\n🔴 Critical (>14 days):")
        for p, a in critical: print(f"  {p} ({a}d)")
    if no_date:
        print("\n❓ Missing last-reviewed:")
        for p in no_date: print(f"  {p}")
    return 0 if not critical else 1

if __name__ == '__main__':
    sys.exit(check_freshness())
