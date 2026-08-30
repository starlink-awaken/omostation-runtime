#!/usr/bin/env python3
"""KEMS Bootstrap —  generate a new KEMS project directory."""
import os, sys, shutil
from datetime import date

KEMS_ROOT = os.environ.get('KEMS_ROOT', os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
FRAMEWORK = os.path.join(KEMS_ROOT, '.kems')

def bootstrap(target_dir, project_name):
    target = os.path.abspath(os.path.expanduser(target_dir))
    if os.path.exists(target) and os.listdir(target):
        print(f"Target exists and not empty: {target}")
        return 1
    os.makedirs(target, exist_ok=True)
    today = date.today().isoformat()

    # Copy framework
    print(f"Bootstrapping: {project_name}")
    shutil.copytree(FRAMEWORK, os.path.join(target, '.kems'), dirs_exist_ok=True)

    # Project dirs
    for d in ['_control','_entities','_strategy','_runtime/workflows','_runtime/sops',
              '_runtime/agents','_runtime/cases','_gates','_integrations','_reference',
              '_archive','00-overview','10-operations']:
        os.makedirs(os.path.join(target, d), exist_ok=True)

    # CLAUDE.md
    with open(os.path.join(target, 'CLAUDE.md'), 'w') as f:
        f.write(f"# {project_name}\n\nKEMS project. Framework: .kems/ | Data: root.\n\n## Entry actions\n1. Read .kems/_onboarding/01-quickstart.md\n2. Read _control/STATE.md\n3. Route via .kems/_scenarios/\n\n## Routing\n- New info -> .kems/_protocol/01-write-contract.md\n- Output -> .kems/_methods/03-tactics-pipeline.md\n- Audit -> _runtime/sops/02\n- Strategy -> .kems/_methods/02-strategy-ale.md\n")

    # STATE.md
    with open(os.path.join(target, '_control', 'STATE.md'), 'w') as f:
        f.write(f"# STATE\n\nProject: {project_name} | Created: {today}\n\n## Phase\nstartup\n\n## Signals\n- info {today} project initialized\n")

    # README
    with open(os.path.join(target, 'README.md'), 'w') as f:
        f.write(f"# {project_name}\n\nCreated: {today}\n\nSee .kems/_scenarios/01-greenfield.md for getting started.\n")

    count = len(list(os.walk(target)))
    print(f"Done: {target} ({count} entries)")
    return 0

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 bootstrap.py <target-dir> [project-name]")
        sys.exit(1)
    name = sys.argv[2] if len(sys.argv) > 2 else os.path.basename(sys.argv[1])
    sys.exit(bootstrap(sys.argv[1], name))
