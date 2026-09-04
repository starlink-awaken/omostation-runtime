#!/usr/bin/env python3
"""kems — KEMS project bootstrap & management CLI."""
import argparse
import json
import os
import shutil
import sys
from datetime import date

KEMS_HOME = os.environ.get("KEMS_HOME", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
FRAMEWORK = os.path.join(KEMS_HOME, '.kems')
VERSION_FILE = os.path.join(KEMS_HOME, 'INDEX.json')

def get_version():
    try:
        with open(VERSION_FILE) as f:
            return json.load(f).get('version', 'unknown')
    except: return 'unknown'

def cmd_init(args):
    target = os.path.abspath(os.path.expanduser(args.dir))
    name = args.name or os.path.basename(target.rstrip('/'))

    if os.path.exists(target) and os.listdir(target):
        if not args.force:
            print(f"❌ {target} exists and is not empty. Use --force to overwrite.")
            return 1
        print(f"⚠️  Overwriting existing directory: {target}")

    os.makedirs(target, exist_ok=True)
    today = date.today().isoformat()

    # Copy framework
    shutil.copytree(FRAMEWORK, os.path.join(target, '.kems'), dirs_exist_ok=True)

    # Project directories
    for d in ['_control', '_entities', '_strategy',
              '_runtime/workflows', '_runtime/sops', '_runtime/agents', '_runtime/cases',
              '_gates', '_integrations', '_reference',
              '_archive', '00-overview', '10-operations']:
        os.makedirs(os.path.join(target, d), exist_ok=True)

    # CLAUDE.md
    with open(os.path.join(target, 'CLAUDE.md'), 'w') as f:
        f.write(f"# {name}\n\n")
        f.write(f"KEMS project · v{get_version()} · {today}\n\n")
        f.write("## Entry\n")
        f.write("1. Read .kems/_scenarios/01-greenfield.md\n")
        f.write("2. Fill _entities/ and _strategy/\n\n")
        f.write("## Quick Routes\n")
        f.write("- New info → .kems/_protocol/01-write-contract.md\n")
        f.write("- Output → .kems/_methods/03-tactics-pipeline.md\n")
        f.write("- Audit → _runtime/sops/02-每周审计SOP.md\n")
        f.write("- Strategy → .kems/_methods/02-strategy-ale.md\n")

    # STATE.md
    with open(os.path.join(target, '_control', 'STATE.md'), 'w') as f:
        f.write(f"# STATE\n\n{name} · {today}\n\n## Phase\nstartup\n\n## Signals\n- info {today} kems init\n")

    # README
    with open(os.path.join(target, 'README.md'), 'w') as f:
        f.write(f"# {name}\n\nKEMS · {today}\n\n→ .kems/_scenarios/01-greenfield.md\n")

    # Entity templates with structure
    for et in ['persons', 'organizations', 'projects', 'events', 'documents']:
        label = et.capitalize()
        fpath = os.path.join(target, '_entities', f'{et}.md')
        if not os.path.exists(fpath):
            with open(fpath, 'w') as f:
                f.write(f"# {label}\n\n## Template\n\n```\n## [entity-id]\n- name:\n- role/type:\n- trust: confirmed ✅\n```\n")

    # Strategy templates
    for sf in ['goals', 'tasks', 'results', 'reviews', 'feedback']:
        label = sf.capitalize()
        fpath = os.path.join(target, '_strategy', f'{sf}.md')
        if not os.path.exists(fpath):
            with open(fpath, 'w') as f:
                f.write(f"# {label}\n\n_({name} · {today})_\n")

    # Domain stub
    with open(os.path.join(target, '00-overview', 'README.md'), 'w') as f:
        f.write(f"# {name} — Overview\n\nDomain knowledge index.\n")

    count = len(list(os.walk(target)))
    version = get_version()
    print(f"✅ KEMS v{version} · {name}")
    print(f"   {target}")
    print(f"   {count} entries · ready")
    print(f"   Next: cd {os.path.basename(target)} && fill _entities/ _strategy/")
    return 0

def cmd_version(args):
    print(f"KEMS v{get_version()}")
    print(f"Home: {KEMS_HOME}")
    return 0

def cmd_health(args):
    """Run freshness + frontmatter checks on target or CWD"""
    target = os.path.abspath(args.dir) if args.dir else os.getcwd()
    scripts = os.path.join(target, '.kems', '_scripts')
    for s in ['check-freshness.py', 'check-frontmatter.py']:
        spath = os.path.join(scripts, s)
        if os.path.exists(spath):
            print(f"--- {s} ---")
            os.system(f"python3 {spath}")
    return 0

def main():
    p = argparse.ArgumentParser(prog='kems', description='KEMS — Knowledge Engineering Methodology System')
    p.add_argument('--version', action='store_true')
    subs = p.add_subparsers(dest='command')

    init_p = subs.add_parser('init', help='Bootstrap a new KEMS project')
    init_p.add_argument('dir', help='Target directory')
    init_p.add_argument('name', nargs='?', help='Project name (default: dir basename)')
    init_p.add_argument('--force', '-f', action='store_true', help='Overwrite existing directory')
    init_p.set_defaults(func=cmd_init)

    ver_p = subs.add_parser('version', help='Show version')
    ver_p.set_defaults(func=cmd_version)

    health_p = subs.add_parser('health', help='Run health checks')
    health_p.add_argument('dir', nargs='?', help='Project directory (default: CWD)')
    health_p.set_defaults(func=cmd_health)

    args = p.parse_args()
    if args.version and not args.command:
        return cmd_version(args)
    if not args.command:
        p.print_help()
        return 0
    return args.func(args)

if __name__ == '__main__':
    sys.exit(main())
