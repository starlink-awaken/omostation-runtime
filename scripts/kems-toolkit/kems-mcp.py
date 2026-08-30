#!/usr/bin/env python3
"""KEMS MCP Server — exposes KEMS project operations as MCP stdio tools."""
import os, sys, json, re, subprocess
from datetime import date

KEMS_HOME = os.environ.get("KEMS_HOME", os.path.expanduser("~/Documents/学习进化/体系/KEMS"))

def _json_err(msg): return json.dumps({"error": msg})

def tool_init(project_dir: str, project_name: str = None):
    import shutil
    fw = os.path.join(KEMS_HOME, '.kems')
    if not os.path.isdir(fw): return _json_err(f"Framework: {KEMS_HOME}/.kems")
    target = os.path.abspath(os.path.expanduser(project_dir))
    name = project_name or os.path.basename(target.rstrip('/'))
    if os.path.exists(target) and os.listdir(target): return _json_err(f"{target} not empty")
    os.makedirs(target, exist_ok=True)
    today = date.today().isoformat()
    shutil.copytree(fw, os.path.join(target, '.kems'), dirs_exist_ok=True)
    for d in ['_control','_entities','_strategy','_runtime/workflows','_runtime/sops',
              '_runtime/agents','_runtime/cases','_gates','_integrations','_reference',
              '_archive','00-overview']:
        os.makedirs(os.path.join(target, d), exist_ok=True)
    with open(os.path.join(target, 'CLAUDE.md'), 'w') as f:
        f.write(f"# {name}\n\nKEMS · {today}\n\n→ .kems/_scenarios/01-greenfield.md\n")
    with open(os.path.join(target, 'README.md'), 'w') as f: f.write(f"# {name}\n\n{today}\n")
    for et in ['persons','organizations','projects','events','documents']:
        with open(os.path.join(target, '_entities', f'{et}.md'), 'w') as f:
            f.write(f"# {et.capitalize()}\n\n_({name})_\n")
    return json.dumps({"project": name, "dir": target, "entries": len(list(os.walk(target))), "status": "created"})

def tool_health(project_dir: str):
    target = os.path.abspath(os.path.expanduser(project_dir))
    if not os.path.isdir(target): return _json_err(f"Not found: {target}")
    total, no_date, ents, sigs = 0, 0, 0, 0
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '_archive']
        for fn in files:
            if not fn.endswith('.md'): continue; total += 1
            fpath = os.path.join(root, fn)
            with open(fpath, errors='ignore') as f: c = f.read(500)
            if not re.search(r'last-reviewed:\s*\d{4}-\d{2}-\d{2}', c): no_date += 1
            if fn == 'persons.md': ents += len(re.findall(r'##\s+\[', c))
            if fn == 'signals.md': sigs += len(re.findall(r'[-*]\s+[✅⚠️ℹ️🔴]', c))
    rate = round(no_date / max(total, 1) * 100)
    return json.dumps({"files": total, "stale_pct": rate, "entities": ents, "signals": sigs,
                       "health": "ok" if rate < 20 else "warn" if rate < 50 else "critical"})

def tool_query(project_dir: str, entity_type: str, query: str = ""):
    target = os.path.abspath(os.path.expanduser(project_dir))
    fpath = os.path.join(target, '_entities', f'{entity_type}.md')
    if not os.path.isfile(fpath): return _json_err(f"No {entity_type}.md")
    with open(fpath) as f: c = f.read()
    entries = re.findall(r'##\s+\[([^\]]+)\]\s*\n((?:(?!##\s+\[).*\n)*)', c, re.MULTILINE)
    r = []
    for eid, body in entries:
        if query and query.lower() not in eid.lower() and query.lower() not in body.lower(): continue
        nm = re.search(r'[-*]\s*(?:name|名称)[:：]\s*(.*)', body)
        tr = re.search(r'trust\w*\s*[:：]\s*(\w+)', body)
        r.append({"id": eid.strip(), "name": nm.group(1).strip() if nm else "", "trust": tr.group(1) if tr else "?"})
    return json.dumps({"type": entity_type, "count": len(r), "entries": r[:20]})

def tool_check(project_dir: str, check: str):
    target = os.path.abspath(os.path.expanduser(project_dir))
    m = {"freshness": "check-freshness.py", "frontmatter": "check-frontmatter.py", "index": "check-index.py"}
    if check not in m: return _json_err(f"Unknown: {check}. Options: {list(m)}")
    sp = os.path.join(target, '.kems', '_scripts', m[check])
    if not os.path.isfile(sp): return _json_err(f"Script: {sp}")
    r = subprocess.run(['python3', sp], capture_output=True, text=True, timeout=15, cwd=target)
    return json.dumps({"check": check, "exit": r.returncode, "output": r.stdout[:2000]})

def tool_workflows():
    wf = {}
    for d in ['_scenarios', '_runtime/workflows']:
        dp = os.path.join(KEMS_HOME, '.kems', d) if d == '_scenarios' else os.path.join(KEMS_HOME, d)
        if not os.path.isdir(dp): continue
        for fn in sorted(os.listdir(dp)):
            if fn.endswith('.md') and fn != 'INDEX.md':
                with open(os.path.join(dp, fn)) as f: h = f.read(200)
                m = re.search(r'#\s+(.*)', h)
                wf[f"{d.split('/')[-1]}/{fn}"] = m.group(1) if m else fn
    return json.dumps({"workflows": wf})

def tool_version():
    v = "unknown"
    try:
        with open(os.path.join(KEMS_HOME, 'INDEX.json')) as f: v = json.load(f).get('version', v)
    except: pass
    return json.dumps({"version": v, "home": KEMS_HOME})

TOOLS = {
    "kems_init": (tool_init, {
        "description": "Initialize a KEMS project directory with .kems framework, control plane, entities, and strategy templates.",
        "inputSchema": {"type": "object", "properties": {
            "project_dir": {"type": "string", "description": "Target directory path"},
            "project_name": {"type": "string", "description": "Optional project name"}
        }, "required": ["project_dir"]}
    }),
    "kems_health": (tool_health, {
        "description": "Health check: file count, staleness rate, entities, signals.",
        "inputSchema": {"type": "object", "properties": {
            "project_dir": {"type": "string", "description": "Project directory"}
        }, "required": ["project_dir"]}
    }),
    "kems_query_entity": (tool_query, {
        "description": "Query entities from a KEMS project by type with optional filter.",
        "inputSchema": {"type": "object", "properties": {
            "project_dir": {"type": "string", "description": "Project directory"},
            "entity_type": {"type": "string", "description": "persons/organizations/projects/events/documents"},
            "query": {"type": "string", "description": "Optional filter string"}
        }, "required": ["project_dir", "entity_type"]}
    }),
    "kems_run_check": (tool_check, {
        "description": "Run a check script: freshness, frontmatter, or index.",
        "inputSchema": {"type": "object", "properties": {
            "project_dir": {"type": "string", "description": "Project directory"},
            "check": {"type": "string", "description": "freshness | frontmatter | index"}
        }, "required": ["project_dir", "check"]}
    }),
    "kems_list_workflows": (tool_workflows, {
        "description": "List all KEMS workflows and scenarios.",
        "inputSchema": {"type": "object", "properties": {}}
    }),
    "kems_version": (tool_version, {
        "description": "Show KEMS version and home.",
        "inputSchema": {"type": "object", "properties": {}}
    }),
}

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--describe":
        print(json.dumps({"tools": [{"name": k, **v[1]} for k, v in TOOLS.items()]}))
        return
    for line in sys.stdin:
        try: req = json.loads(line)
        except: continue
        m, rid = req.get("method"), req.get("id")
        if m == "tools/list":
            resp = {"jsonrpc": "2.0", "id": rid, "result": {"tools": [{"name": k, **v[1]} for k, v in TOOLS.items()]}}
        elif m == "tools/call":
            name = req.get("params", {}).get("name", "")
            args = req.get("params", {}).get("arguments", {})
            fn, _ = TOOLS.get(name, (None, None))
            if fn:
                result = fn(**args)
                resp = {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": result}]}}
            else:
                resp = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown: {name}"}}
        else: continue
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()

if __name__ == '__main__':
    main()
