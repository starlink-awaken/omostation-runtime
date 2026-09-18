#!/usr/bin/env python3
"""refresh-indexes.py — 索引刷新

重新生成域内两份索引：
  1. _knowledge/索引目录/全局文件索引.md
     — 扫描全域文件，输出 frontmatter + 文件类型分布 + 一级目录统计 + 目录树
  2. _knowledge/索引目录/知识面目录摘要.md
     — 仅扫描 _knowledge/，按一级目录统计

排除目录/文件：.git、node_modules、__pycache__、.venv、.DS_Store、.ocr_text 内部隐藏等。
输出刷新前后文件数对比。

用法：
  python3 refresh-indexes.py --root <域根>
退出码：0=刷新成功，1=失败。

域身份从 <域根>/DOMAIN.yaml 读取（id、display_name）；
缺失时回退为目录名，并打印告警，不再硬编码 work-weijian / 卫健委。
"""
import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

EXCLUDE_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".omc", ".crush", ".github"}
EXCLUDE_FILES = {".DS_Store"}


def resolve_root(raw):
    p = Path(raw).expanduser().resolve()
    if not p.is_dir():
        sys.exit(f"❌ 域根不存在: {p}")
    return p


def load_domain_info(root: Path) -> dict:
    """从 <root>/DOMAIN.yaml 读取域身份。

    返回 {"id": str, "display_name": str, "short_name": str}。
    DOMAIN.yaml 缺失或解析失败时回退为目录名，short_name = 目录名。
    """
    info = {
        "id": root.name,
        "display_name": root.name,
        "short_name": root.name,
    }
    dy = root / "DOMAIN.yaml"
    if not dy.is_file():
        print(f"⚠️  域根无 DOMAIN.yaml（{root}），域身份回退为目录名: {root.name}")
        return info

    raw_text = dy.read_text(encoding="utf-8")
    if yaml is not None:
        try:
            data = yaml.safe_load(raw_text) or {}
        except Exception as e:
            print(f"⚠️  DOMAIN.yaml 解析失败（{e}），域身份回退为目录名: {root.name}")
            return info
        info["id"] = str(data.get("id") or root.name)
        info["display_name"] = str(data.get("display_name") or info["id"])
    else:
        # 无 pyyaml 时用简易键值解析
        kv = {}
        for line in raw_text.splitlines():
            line = line.strip()
            if ":" in line and not line.startswith(("-", "#")):
                k, _, v = line.partition(":")
                v = v.strip()
                # 去除 YAML 风格首尾引号
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                    v = v[1:-1]
                kv[k.strip()] = v
        info["id"] = kv.get("id", root.name)
        info["display_name"] = kv.get("display_name", info["id"])

    # short_name: display_name 的最后一段，例如 "A/B" -> "B"
    dn = info["display_name"]
    info["short_name"] = dn.rstrip("/").rsplit("/", 1)[-1] if "/" in dn else dn
    return info


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def scan_files(root, subdir=None):
    """扫描 root（或 root/subdir），返回 list[(Path rel, size_bytes)]。"""
    base = root / subdir if subdir else root
    results = []
    if not base.is_dir():
        return results
    for dirpath, dirnames, filenames in os.walk(base):
        # 原地过滤排除目录
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn in EXCLUDE_FILES or fn.startswith("."):
                continue
            fp = Path(dirpath) / fn
            try:
                size = fp.stat().st_size
            except OSError:
                size = 0
            rel = fp.relative_to(root)
            results.append((rel, size))
    return results


def ext_group(name):
    if "." not in name:
        return "(无扩展名)"
    return "." + name.rsplit(".", 1)[-1].lower()


def build_global_index(root, info):
    files = scan_files(root)
    total = len(files)
    total_size = sum(s for _, s in files)
    domain_id = info["id"]
    short_name = info["short_name"]

    # 文件类型分布
    by_ext = defaultdict(int)
    for rel, _ in files:
        by_ext[ext_group(rel.name)] += 1
    ext_rows = sorted(by_ext.items(), key=lambda x: -x[1])

    # 一级目录统计
    by_top = defaultdict(int)
    for rel, _ in files:
        top = rel.parts[0] if len(rel.parts) > 1 else "(根目录)"
        by_top[top] += 1
    top_rows = sorted(by_top.items(), key=lambda x: -x[1])

    # 目录树：按一级目录分组，列文件
    tree = defaultdict(list)
    for rel, size in files:
        top = rel.parts[0] if len(rel.parts) > 1 else "(根目录)"
        tree[top].append((str(rel), size))

    lines = []
    lines.append("---")
    lines.append('title: "全局文件索引"')
    lines.append(f"domain: {domain_id}")
    lines.append(f"date: {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("status: 已采纳")
    lines.append("type: meta")
    lines.append("owner: xiamingxing")
    lines.append(f"created: {datetime.now().strftime('%Y-%m-%d')}")
    lines.append(f"last-reviewed: {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("supersedes: 无")
    lines.append("superseded-by: 无")
    lines.append("---")
    lines.append("")
    lines.append(f"# {short_name}全局文件索引")
    lines.append("")
    lines.append(f"> 自动生成: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 总文件数: {total} | 总容量: {human_size(total_size)}")
    lines.append("> 生成器: kems-v2/refresh-indexes.py --root 参数化")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 一、全局概览")
    lines.append("")
    lines.append("### 文件类型分布")
    lines.append("")
    lines.append("| 类型 | 数量 | 占比 |")
    lines.append("|------|:----:|:----:|")
    for ext, cnt in ext_rows:
        pct = f"{cnt / total * 100:.1f}%" if total else "0%"
        lines.append(f"| {ext} | {cnt} | {pct} |")
    lines.append("")
    lines.append("### 一级目录文件数")
    lines.append("")
    lines.append("| 目录 | 文件数 |")
    lines.append("|------|:----:|")
    for top, cnt in top_rows:
        lines.append(f"| {top} | {cnt} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 二、目录树")
    for top in sorted(tree.keys()):
        entries = sorted(tree[top])
        lines.append("")
        lines.append(f"### {top}/ ({len(entries)}个文件)")
        for rel, size in entries:
            lines.append(f"- `{rel}` ({human_size(size)})")
    lines.append("")
    return "\n".join(lines), total


def build_knowledge_summary(root, info):
    """仅扫描 _knowledge/，按一级目录统计。"""
    know = root / "_knowledge"
    files = scan_files(root, "_knowledge")
    total = len(files)
    domain_id = info["id"]
    short_name = info["short_name"]

    by_top = defaultdict(int)
    for rel, _ in files:
        # rel 形如 _knowledge/业务资料/xxx
        parts = rel.parts
        if len(parts) >= 2:
            top = parts[1]
        else:
            top = "(根)"
        by_top[top] += 1
    top_rows = sorted(by_top.items(), key=lambda x: -x[1])

    lines = []
    lines.append("---")
    lines.append('title: "知识面目录摘要"')
    lines.append(f"domain: {domain_id}")
    lines.append(f"date: {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("status: 已采纳")
    lines.append("type: meta")
    lines.append("owner: xiamingxing")
    lines.append(f"created: {datetime.now().strftime('%Y-%m-%d')}")
    lines.append(f"last-reviewed: {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("supersedes: 无")
    lines.append("superseded-by: 无")
    lines.append("---")
    lines.append("")
    lines.append(f"# {short_name}知识面目录摘要索引")
    lines.append("")
    lines.append("> **定位：** _knowledge 顶层目录内容摘要，快速定位\"哪个目录讲什么\"。")
    lines.append(f"> **生成：** {datetime.now().strftime('%Y-%m-%d')} | 知识面总计 {total} 文件")
    lines.append("> **生成器：** kems-v2/refresh-indexes.py --root 参数化")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 一、_knowledge 一级目录文件数")
    lines.append("")
    lines.append("| 目录 | 文件数 |")
    lines.append("|------|:----:|")
    for top, cnt in top_rows:
        lines.append(f"| {top}/ | {cnt} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*生成：{datetime.now().strftime('%Y-%m-%d')} | 信息科 / xiamingxing*")
    lines.append("")
    return "\n".join(lines), total


def main():
    ap = argparse.ArgumentParser(description="刷新全局文件索引与知识面目录摘要")
    ap.add_argument("--root", required=True, help="域根绝对路径")
    args = ap.parse_args()
    domain = resolve_root(args.root)
    info = load_domain_info(domain)

    print("=" * 60)
    print("🔄 KEMS 索引刷新")
    print(f"   域: {info['short_name']} ({info['id']})")
    print(f"   根: {domain}")
    print("=" * 60)

    idx_dir = domain / "_knowledge" / "索引目录"
    idx_dir.mkdir(parents=True, exist_ok=True)
    global_path = idx_dir / "全局文件索引.md"
    summary_path = idx_dir / "知识面目录摘要.md"

    # 刷新前文件数
    before_global = 0
    if global_path.is_file():
        before_global = len(scan_files(domain))
    before_summary = 0
    if summary_path.is_file():
        before_summary = len(scan_files(domain, "_knowledge"))

    # 生成全局索引
    global_text, global_total = build_global_index(domain, info)
    global_path.write_text(global_text, encoding="utf-8")
    print("\n✅ 全局文件索引.md 已刷新")
    print(f"   刷新前全域文件数: {before_global} → 刷新后: {global_total}")

    # 生成知识面摘要
    summary_text, summary_total = build_knowledge_summary(domain, info)
    summary_path.write_text(summary_text, encoding="utf-8")
    print("\n✅ 知识面目录摘要.md 已刷新")
    print(f"   刷新前 _knowledge 文件数: {before_summary} → 刷新后: {summary_total}")

    print("\n" + "=" * 60)
    print("✅ 索引刷新完成")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    main()
