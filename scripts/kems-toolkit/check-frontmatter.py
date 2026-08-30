#!/usr/bin/env python3
"""检查所有 Markdown 文件的 frontmatter 字段完整性。"""
import os, re, sys

REQUIRED = ['title', 'status', 'created']
EXPECTED = ['title', 'status', 'type', 'created', 'last-reviewed', 'tags']
SKIP_DIRS = {'_archive', '.git', '__pycache__'}
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def check_frontmatter():
    missing, incomplete, ok = [], [], []
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in SKIP_DIRS]
        for fname in files:
            if not fname.endswith('.md'):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath) as f:
                content = f.read()
            # Extract frontmatter
            m = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
            if not m:
                # Check if it's a CLAUDE.md or README (may not need frontmatter)
                if fname in ('CLAUDE.md', 'README.md', 'AGENT.md', 'INDEX.md'):
                    continue
                missing.append(fpath.replace(BASE+'/',''))
                continue
            fm = m.group(1)
            found = set(re.findall(r'^(\w[\w-]*):', fm, re.MULTILINE))
            rel = fpath.replace(BASE+'/','')
            miss = [f for f in REQUIRED if f not in found]
            partial = [f for f in EXPECTED if f not in found]
            if miss:
                missing.append((rel, miss))
            elif len(partial) > 0:
                incomplete.append((rel, partial))
            else:
                ok.append(rel)
    
    total = len(ok) + len(incomplete) + len(missing)
    print(f"=== KEMS Frontmatter Check ===")
    print(f"Total: {total} | OK: {len(ok)} | Partial: {len(incomplete)} | Missing: {len(missing)}")
    if missing:
        print(f"\n❌ Missing required fields:")
        for p, fields in missing: print(f"  {p}: missing {fields}")
    if incomplete:
        print(f"\n⚠️  Missing expected fields:")
        for p, fields in incomplete: print(f"  {p}: missing {fields}")
    return 0 if not missing else 1

if __name__ == '__main__':
    sys.exit(check_frontmatter())
