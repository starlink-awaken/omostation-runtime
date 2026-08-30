#!/usr/bin/env python3
"""从 KEMS 实际数据生成 Dashboard HTML。读取 _control/ + _gates/ + _strategy/ 的最新数据。"""
import os, re, sys, json
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(BASE, '_outputs', 'dashboard.html')

def read_signals():
    """读取最近 5 条信号"""
    signals_file = os.path.join(BASE, '_control', 'signals.md')
    if not os.path.exists(signals_file):
        return []
    with open(signals_file) as f:
        content = f.read()
    entries = re.findall(r'[-*]\s+(✅|⚠️|ℹ️|🔴)\s+(.+?)(?:\n|$)', content)
    return [{"type": t, "text": txt.strip()} for t, txt in entries[-5:]]

def read_tasks():
    """读取任务看板"""
    tasks_file = os.path.join(BASE, '_strategy', '04-tasks.md')
    if not os.path.exists(tasks_file):
        return []
    with open(tasks_file) as f:
        content = f.read()
    entries = re.findall(r'\|\s*([A-Za-z0-9_-]+)\s*\|\s*(.+?)\s*\|\s*(\w[\w-]*)\s*\|\s*(\w[\w-]*)\s*\|', content)
    return [{"id": e[0], "name": e[1].strip(), "status": e[2], "pri": e[3]} for e in entries]

def read_freshness():
    """从上次 check-freshness 输出中提取数据"""
    # In production, call the script and parse output
    # For now, compute directly
    total, stale = 0, 0
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '_archive']
        for fname in files:
            if fname.endswith('.md'):
                total += 1
                fpath = os.path.join(root, fname)
                with open(fpath, errors='ignore') as f:
                    content = f.read(500)
                m = re.search(r'last-reviewed:\s*(\d{4}-\d{2}-\d{2})', content)
                if not m:
                    stale += 1
    rate = round(stale / max(total, 1) * 100)
    return total, stale, rate

def generate():
    today = date.today().isoformat()
    signals = read_signals()
    tasks = read_tasks()
    total, stale, rate = read_freshness()
    health = 100 - rate
    
    # Build metrics
    metrics = [
        {"name":"文件过期率", "val":f"{rate}%", "pct":rate, "cls":"warn" if rate > 10 else "ok"},
        {"name":"健康率", "val":f"{health}%", "pct":health, "cls":"ok" if health > 80 else "warn"},
        {"name":"信号数", "val":str(len(signals)), "pct":min(len(signals)*20, 100), "cls":"ok"},
        {"name":"任务数", "val":str(len(tasks)), "pct":min(len(tasks)*25, 100), "cls":"ok"},
    ]
    
    # Generate HTML
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta http-equiv="refresh" content="3600"><title>KEMS Dashboard</title>
<style>
:root{{color-scheme:light;--bg:#fff;--fg:#222;--card:#f5f5f5}}
body{{font-family:-apple-system,system-ui,sans-serif;margin:24px;background:var(--bg);color:var(--fg)}}
h1{{font-size:1.3em;margin-bottom:4px}}h2{{font-size:1em;color:#666;margin-top:20px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}}
.card{{background:var(--card);border-radius:8px;padding:14px}}
.card .label{{font-size:0.75em;color:#888;text-transform:uppercase}}
.card .value{{font-size:1.6em;font-weight:700;margin:4px 0}}
.metrics{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}}
.metric{{padding:8px;background:white;border-radius:4px}}
.metric .name{{font-size:0.8em;color:#888}}
.metric .val{{font-size:1.1em;font-weight:600}}
.bar{{height:4px;border-radius:2px;margin-top:4px;background:#e0e0e0}}
.bar-fill{{height:4px;border-radius:2px}}
.ok{{color:#2e7d32}}.warn{{color:#ef6c00}}.crit{{color:#c62828}}
table{{width:100%;border-collapse:collapse;margin-top:8px}}
th,td{{text-align:left;padding:6px;border-bottom:1px solid#e0e0e0;font-size:0.85em}}
th{{color:#888;font-weight:500}}
.footer{{margin-top:24px;font-size:0.75em;color:#aaa}}
</style></head>
<body>
<h1>KEMS Dashboard</h1>
<p style="color:#888;font-size:0.85em">{today} · 自动刷新 · 每60分钟</p>
<div class="grid">
  <div class="card"><div class="label">总文件数</div><div class="value">{total}</div></div>
  <div class="card"><div class="label">健康率</div><div class="value {'ok' if health>80 else 'warn'}">{health}%</div></div>
  <div class="card"><div class="label">信号数</div><div class="value">{len(signals)}</div></div>
  <div class="card"><div class="label">任务数</div><div class="value">{len(tasks)}</div></div>
</div>
<h2>质量度量</h2>
<div class="metrics">
"""
    for m in metrics:
        html += f'<div class="metric"><div class="name">{m["name"]}</div><div class="val {m["cls"]}">{m["val"]}</div><div class="bar"><div class="bar-fill" style="width:{m["pct"]}%;background:{"#c62828" if m["cls"]=="crit" else "#ef6c00" if m["cls"]=="warn" else "#2e7d32"}"></div></div></div>\n'
    
    html += """</div>
<h2>信号日志（最近）</h2>
<table><thead><tr><th>类型</th><th>信号</th></tr></thead><tbody>
"""
    for s in signals:
        html += f'<tr><td>{s["type"]}</td><td>{s["text"]}</td></tr>\n'
    if not signals:
        html += '<tr><td colspan="2" style="color:#aaa">暂无信号</td></tr>\n'
    
    html += """</tbody></table>
<h2>任务看板</h2>
<table><thead><tr><th>ID</th><th>任务</th><th>状态</th><th>优先级</th></tr></thead><tbody>
"""
    for t in tasks:
        html += f'<tr><td>{t["id"]}</td><td>{t["name"]}</td><td>{t["status"]}</td><td>{t["pri"]}</td></tr>\n'
    if not tasks:
        html += '<tr><td colspan="4" style="color:#aaa">暂无任务</td></tr>\n'
    
    html += f"""</tbody></table>
<p class="footer">KEMS v3.3 · generated {today} · <code>python3 _scripts/generate-dashboard.py</code></p>
</body></html>"""
    
    with open(OUTPUT, 'w') as f:
        f.write(html)
    print(f"Dashboard generated: {OUTPUT} ({len(html)} bytes)")
    print(f"  Files: {total} | Health: {health}% | Signals: {len(signals)} | Tasks: {len(tasks)}")
    return 0

if __name__ == '__main__':
    sys.exit(generate())
