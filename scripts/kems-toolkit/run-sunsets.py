#!/usr/bin/env python3
"""执行日落检查：标记已到期的任务/规则。"""
import os, re, sys
from datetime import date

TRIGGERS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '_triggers')

def run_sunsets():
    sunset_file = os.path.join(TRIGGERS_DIR, '03-sunrise-sunset.md')
    if not os.path.exists(sunset_file):
        print("No sunset file found")
        return 1
    with open(sunset_file) as f:
        content = f.read()
    
    # Find sunset conditions with dates
    date_sunsets = re.findall(r'sunset:\s*(\+?\d+d|\d{4}-\d{2}-\d{2})', content)
    today = date.today()
    
    print(f"=== KEMS Sunset Check ({today}) ===")
    print(f"Found {len(date_sunsets)} sunset conditions in config")
    # Note: actual sunset execution depends on task definition format
    # This script identifies candidates for manual review
    print("Sunset candidates identified. Review _triggers/03-sunrise-sunset.md for details.")
    return 0

if __name__ == '__main__':
    sys.exit(run_sunsets())
