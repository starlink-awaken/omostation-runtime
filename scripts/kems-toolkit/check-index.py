#!/usr/bin/env python3
"""检查 INDEX.md 中的条目与实际文件的一致性。"""
import os, re, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def check_index():
    # Collect all actual .md files
    actual = set()
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '_archive']
        for fname in files:
            if fname.endswith('.md'):
                actual.add(os.path.relpath(os.path.join(root, fname), BASE))
    
    # Parse INDEX.md entries
    index_file = os.path.join(BASE, 'INDEX.md')
    if not os.path.exists(index_file):
        print("No root INDEX.md found")
        return 1
    with open(index_file) as f:
        content = f.read()
    # Extract markdown links like [text](path)
    indexed = set(re.findall(r'\]\(([^)]+\.md)\)', content))
    
    missing_in_index = actual - indexed
    missing_on_disk = indexed - actual
    
    print(f"=== KEMS INDEX Check ===")
    print(f"Actual files: {len(actual)} | Indexed: {len(indexed)}")
    print(f"In INDEX, not on disk: {len(missing_on_disk)}")
    print(f"On disk, not in INDEX: {len(missing_in_index)}")
    if missing_on_disk:
        print(f"\n⚠️  In INDEX but file missing:")
        for p in sorted(missing_on_disk): print(f"  {p}")
    if missing_in_index:
        print(f"\n⚠️  On disk but not in INDEX:")
        for p in sorted(missing_in_index): print(f"  {p}")
    completeness = round(len(actual & indexed) / max(len(actual),1) * 100)
    print(f"\nINDEX completeness: {completeness}% {'✅' if completeness >= 95 else '⚠️ <95%'}")
    return 0 if len(missing_in_index) == 0 else 1

if __name__ == '__main__':
    sys.exit(check_index())
