#!/usr/bin/env python3
"""model-ask.py — 确定性检索问答（v1，不依赖 LLM）

在 `_entities/models/*.md`（模型文档）与 `_entities/facts/*.yaml`（事实）中做
关键词检索，按命中次数排序返回 top-k。**不调用 LLM**，仅做确定性关键词匹配；
`--llm` 参数为占位，待 Workspace runtime LLM gateway 接入后实现。

用法：
  python3 model-ask.py --root <域根> --query "三医联动"
  python3 model-ask.py --root <域根> --query "预算" --type facts --class budget
  python3 model-ask.py --root <域根> --query "电子病历" --type models --top-k 5
  python3 model-ask.py --root <域根> --query "归集" --detail

退出码：0=有召回；1=无召回或参数错误。
"""
import argparse
import re
import sys
from pathlib import Path

import yaml


def resolve_root(raw):
    p = Path(raw).expanduser().resolve()
    if not p.is_dir():
        sys.exit(f"❌ 域根不存在: {p}")
    return p


def split_keywords(query):
    """把查询串拆成关键词：先按空白分词，再按中文逗号/顿号/斜杠切。"""
    parts = re.split(r"[\s,，、/;；]+", query.strip())
    return [p for p in parts if p]


def count_hits(text, kws):
    """统计 text 中命中的关键词数（每个 kw 至少命中一次算 1 分）。"""
    if not text:
        return 0
    t = text.lower()
    return sum(1 for kw in kws if kw.lower() in t)


# ── models 检索 ──
def parse_frontmatter(text):
    """从 markdown 文本中解析 YAML frontmatter（--- ... --- 之间）。"""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    body = text[m.end():]
    return fm, body


def search_models(models_dir, kws, top_k, detail):
    results = []
    if not models_dir.is_dir():
        return results
    for md in sorted(models_dir.glob("*.md")):
        if md.name.lower() == "readme.md":
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, body = parse_frontmatter(text)
        title = fm.get("title", md.stem)
        desc = fm.get("description", "")
        tags = fm.get("tags", []) or []
        tag_str = " ".join(tags) if isinstance(tags, list) else str(tags)

        # 在 frontmatter 字段 + 正文行里找命中
        haystack = f"{title}\n{desc}\n{tag_str}\n{body}"
        score = count_hits(haystack, kws)
        if score == 0:
            continue
        # 找命中行
        hit_lines = []
        for ln in body.splitlines():
            ls = ln.strip()
            if not ls or len(ls) < 4:
                continue
            if count_hits(ls, kws) > 0:
                hit_lines.append(ls)
                if len(hit_lines) >= 3:
                    break
        results.append({
            "score": score,
            "path": str(md.relative_to(models_dir.parent.parent)),
            "title": title,
            "desc": desc,
            "hit_lines": hit_lines,
        })
    results.sort(key=lambda x: (-x["score"], x["path"]))
    return results[:top_k]


# ── facts 检索 ──
def search_facts(facts_dir, kws, top_k, fact_type_filter, detail):
    results = []
    if not facts_dir.is_dir():
        return results
    for yf in sorted(facts_dir.glob("*.yaml")):
        if yf.name == "_index.yaml" or yf.name.endswith(".bak-20260916"):
            continue
        try:
            data = yaml.safe_load(yf.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for f in data.get("facts", []) or []:
            ftype = f.get("type", "")
            if fact_type_filter and ftype != fact_type_filter:
                continue
            stmt = f.get("statement", "")
            src = f.get("source", "")
            summary = f.get("summary", "")
            tags = f.get("tags", []) or []
            tag_str = " ".join(tags) if isinstance(tags, list) else str(tags)
            haystack = f"{stmt}\n{src}\n{summary}\n{tag_str}"
            score = count_hits(haystack, kws)
            if score == 0:
                continue
            results.append({
                "score": score,
                "fid": f.get("fid", "?"),
                "type": ftype,
                "statement": stmt,
                "source": src,
                "trust": f.get("trust", ""),
                "status": f.get("status", ""),
                "file": yf.name,
            })
    results.sort(key=lambda x: (-x["score"], x["fid"]))
    return results[:top_k]


def main():
    ap = argparse.ArgumentParser(description="确定性检索问答 v1（不依赖 LLM）")
    ap.add_argument("--root", required=True, help="域根绝对路径")
    ap.add_argument("--query", required=True, help="查询关键词（空格分隔多词）")
    ap.add_argument("--type", choices=["models", "facts", "all"], default="all",
                    help="检索范围（默认 all）")
    ap.add_argument("--class", dest="fact_class",
                    help="限定 facts 的 type 分类（budget/progress/event/structure/rule/info/indicator/relation/config）")
    ap.add_argument("--top-k", type=int, default=10, help="返回前 N 条（默认 10）")
    ap.add_argument("--detail", action="store_true", help="显示命中条目完整内容")
    ap.add_argument("--llm", action="store_true",
                    help="（占位）待 Workspace runtime LLM gateway 接入后实现")
    args = ap.parse_args()

    if args.llm:
        print("⚠️  --llm 模式待集成：当前 v1 为确定性关键词检索，不调用外部 LLM gateway。")
        print("    已自动降级为 --type all 的关键词检索。\n")

    domain = resolve_root(args.root)
    models_dir = domain / "_entities" / "models"
    facts_dir = domain / "_entities" / "facts"

    kws = split_keywords(args.query)
    if not kws:
        sys.exit("❌ 查询词为空")

    print("=" * 60)
    print(f"🔎 检索: \"{args.query}\"（关键词: {', '.join(kws)}）")
    print(f"   范围: {args.type}   top-k={args.top_k}   detail={args.detail}")
    print("=" * 60)

    any_hit = False

    if args.type in ("models", "all"):
        ms = search_models(models_dir, kws, args.top_k, args.detail)
        print(f"\n── 模型文档（{len(ms)} 条命中）──")
        for i, r in enumerate(ms, 1):
            any_hit = True
            print(f"\n[{i}] score={r['score']}  {r['path']}")
            print(f"    标题: {r['title']}")
            if r["desc"]:
                print(f"    描述: {r['desc']}")
            if args.detail:
                for ln in r["hit_lines"]:
                    print(f"      · {ln[:100]}")
            else:
                if r["hit_lines"]:
                    print(f"    命中行: {r['hit_lines'][0][:80]}")

    if args.type in ("facts", "all"):
        fs = search_facts(facts_dir, kws, args.top_k, args.fact_class, args.detail)
        print(f"\n── 事实条目（{len(fs)} 条命中"
              + (f"，type={args.fact_class}" if args.fact_class else "")
              + "）──")
        for i, r in enumerate(fs, 1):
            any_hit = True
            print(f"\n[{i}] score={r['score']}  {r['fid']}  ({r['type']}, trust={r['trust']}, status={r['status']})")
            print(f"    {r['statement']}")
            if r["source"]:
                print(f"    来源: {r['source']}")

    print("\n" + "=" * 60)
    if not any_hit:
        print("⚠️  无命中。尝试更短的关键词或同义词。")
        print("=" * 60)
        sys.exit(1)
    print("✅ 检索完成")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    main()
