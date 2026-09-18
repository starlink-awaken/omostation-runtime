#!/usr/bin/env python3
"""graph-query.py — 知识图谱查询（v1，纯 Python dict 建图，不依赖 networkx）

把 `_entities/ontology/instances.yaml`（节点）与 `associations.yaml`（边）
在内存里建成有向图，支持：
  --stats                 图统计（节点/边/各类节点数/各关系边数/孤立节点）
  --neighbors <id> [--depth N]
                          实体 N 层邻居（BFS，默认 1 层），输出上下游关系
  --path <source> <target>
                          两实体间最短路径（BFS），输出节点链与关系链
  --by-class <class_id>   按类（如 C4）列出全部实例
  --by-relation <rel_id>   按关系（如 R5）列出全部边
  --search <keyword>      按实体 name/id 关键词搜索

用法：
  python3 graph-query.py --root <域根> --stats
  python3 graph-query.py --root <域根> --neighbors proj-data-collect --depth 2
  python3 graph-query.py --root <域根> --path org-liangxiang sys-emr
  python3 graph-query.py --root <域根> --by-class C4
  python3 graph-query.py --root <域根> --search 良乡

退出码：0=查询成功；1=节点/关系不存在或图构建失败。
"""
import argparse
import sys
from collections import deque
from pathlib import Path

import yaml


def resolve_root(raw):
    p = Path(raw).expanduser().resolve()
    if not p.is_dir():
        sys.exit(f"❌ 域根不存在: {p}")
    return p


def load_yaml(path):
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        sys.exit(f"❌ 找不到 YAML: {path}")
    except yaml.YAMLError as e:
        sys.exit(f"❌ YAML 解析失败 {path}: {e}")


class Graph:
    """纯 Python dict 有向图。adj_out: src -> [(rel, tgt, note)]；adj_in: tgt -> [(rel, src, note)]。"""

    def __init__(self, domain):
        self.domain = domain
        ont = domain / "_entities" / "ontology"
        instances = load_yaml(ont / "instances.yaml")
        associations = load_yaml(ont / "associations.yaml")
        classes = load_yaml(ont / "classes.yaml")
        relations = load_yaml(ont / "relations.yaml")

        # 节点表
        self.nodes = {}
        for i in instances.get("instances", []) or []:
            iid = i.get("id")
            if iid:
                self.nodes[iid] = {
                    "class": i.get("class", "?"),
                    "name": i.get("name", iid),
                    "ref": i.get("ref", ""),
                    "status": i.get("status", ""),
                }
        # 类名 / 关系名映射
        self.class_name = {c.get("id"): c.get("name_cn") or c.get("code") or c.get("id")
                           for c in classes.get("classes", []) or [] if c.get("id")}
        self.rel_name = {r.get("id"): f"{r.get('id')}({r.get('code', '')})"
                         for r in relations.get("relations", []) or [] if r.get("id")}
        # 边表
        self.edges = []  # (source, relation, target, note)
        self.adj_out = {nid: [] for nid in self.nodes}
        self.adj_in = {nid: [] for nid in self.nodes}
        for e in associations.get("edges", []) or []:
            s, r, t = e.get("source"), e.get("relation"), e.get("target")
            note = e.get("note", "")
            if not (s and r and t):
                continue
            self.edges.append((s, r, t, note))
            self.adj_out.setdefault(s, []).append((r, t, note))
            self.adj_in.setdefault(t, []).append((r, s, note))

    # ── 显示辅助 ──
    def node_label(self, nid):
        n = self.nodes.get(nid)
        if not n:
            return f"{nid}(?)"
        cls = n["class"]
        clsname = self.class_name.get(cls, cls)
        return f"{nid}({n['name']}, {cls}/{clsname})"

    def rel_label(self, rid):
        return self.rel_name.get(rid, rid)

    # ── 查询实现 ──
    def stats(self):
        print("=" * 60)
        print("📊 图谱统计")
        print(f"   节点数: {len(self.nodes)}")
        print(f"   边数  : {len(self.edges)}")
        # 各类节点数
        by_cls = {}
        for nid, n in self.nodes.items():
            by_cls.setdefault(n["class"], 0)
            by_cls[n["class"]] += 1
        print("\n   各类节点数：")
        for cid in sorted(by_cls):
            print(f"     {cid:4s} {self.class_name.get(cid, ''):<14s} {by_cls[cid]}")
        # 各关系边数
        by_rel = {}
        for (s, r, t, note) in self.edges:
            by_rel.setdefault(r, 0)
            by_rel[r] += 1
        print("\n   各关系边数：")
        for rid in sorted(by_rel):
            print(f"     {rid:4s} {self.rel_name.get(rid, ''):<18s} {by_rel[rid]}")
        # 孤立节点（无出边也无入边）
        touched = set()
        for (s, r, t, note) in self.edges:
            touched.add(s)
            touched.add(t)
        isolated = [nid for nid in self.nodes if nid not in touched]
        print(f"\n   孤立节点（无任何边）: {len(isolated)}")
        if isolated:
            print(f"     示例: {', '.join(isolated[:8])}{' ...' if len(isolated) > 8 else ''}")
        print("=" * 60)
        return 0

    def neighbors(self, nid, depth=1):
        if nid not in self.nodes:
            print(f"❌ 节点不存在: {nid}")
            return 1
        print("=" * 60)
        print(f"🔗 邻居查询: {self.node_label(nid)}（depth={depth}）")
        print("=" * 60)
        # BFS 分层
        visited = {nid: 0}
        queue = deque([(nid, 0)])
        layers = {0: [nid]}
        while queue:
            cur, d = queue.popleft()
            if d >= depth:
                continue
            for (r, t, note) in self.adj_out.get(cur, []):
                if t not in visited:
                    visited[t] = d + 1
                    layers.setdefault(d + 1, []).append(t)
                    queue.append((t, d + 1))
            for (r, s, note) in self.adj_in.get(cur, []):
                if s not in visited:
                    visited[s] = d + 1
                    layers.setdefault(d + 1, []).append(s)
                    queue.append((s, d + 1))
        for d in range(0, depth + 1):
            if d not in layers:
                continue
            print(f"\n── 第 {d} 层 ──")
            for n in layers[d]:
                if d == 0:
                    print(f"  ● {self.node_label(n)}")
                else:
                    # 找连接到上一层的边
                    ups = layers.get(d - 1, [])
                    conns = []
                    for (r, t, note) in self.adj_out.get(n, []):
                        if t in ups:
                            conns.append(f"{n} --{self.rel_label(r)}--> {t}")
                    for (r, s, note) in self.adj_in.get(n, []):
                        if s in ups:
                            conns.append(f"{s} --{self.rel_label(r)}--> {n}")
                    print(f"  ○ {self.node_label(n)}")
                    for c in conns:
                        print(f"      {c}")
        print("=" * 60)
        return 0

    def shortest_path(self, src, dst):
        if src not in self.nodes:
            print(f"❌ 源节点不存在: {src}")
            return 1
        if dst not in self.nodes:
            print(f"❌ 目标节点不存在: {dst}")
            return 1
        # BFS
        prev = {src: None}
        queue = deque([src])
        found = False
        while queue:
            cur = queue.popleft()
            if cur == dst:
                found = True
                break
            for (r, t, note) in self.adj_out.get(cur, []):
                if t not in prev:
                    prev[t] = (cur, r)
                    queue.append(t)
        print("=" * 60)
        print(f"🛤 最短路径: {src} → {dst}")
        print("=" * 60)
        if not found:
            print("⚠️  两实体间无连通路径")
            print("=" * 60)
            return 1
        # 回溯
        path = []
        cur = dst
        while cur is not None:
            path.append(cur)
            p = prev[cur]
            if p is None:
                break
            cur, r = p
        path.reverse()
        # 输出
        print(f"   路径长度: {len(path) - 1} 跳\n")
        for i, n in enumerate(path):
            if i == 0:
                print(f"   ● {self.node_label(n)}")
            else:
                # 找这条边的 relation
                prev_n = path[i - 1]
                rel = "?"
                for (r, t, note) in self.adj_out.get(prev_n, []):
                    if t == n:
                        rel = r
                        break
                print(f"     │\n     └─ {self.rel_label(rel)} ──▶ {self.node_label(n)}")
        print("=" * 60)
        return 0

    def by_class(self, cid):
        members = [nid for nid, n in self.nodes.items() if n["class"] == cid]
        if not members:
            print(f"❌ 类 {cid} 无实例或类不存在")
            return 1
        print("=" * 60)
        print(f"🏷 类查询: {cid} / {self.class_name.get(cid, '?')}（{len(members)} 个实例）")
        print("=" * 60)
        for nid in sorted(members):
            n = self.nodes[nid]
            print(f"  {nid:32s} {n['name']}")
        print("=" * 60)
        return 0

    def by_relation(self, rid):
        edges = [(s, t, note) for (s, r, t, note) in self.edges if r == rid]
        if not edges:
            print(f"❌ 关系 {rid} 无边或关系不存在")
            return 1
        print("=" * 60)
        print(f"🔗 关系查询: {self.rel_name.get(rid, rid)}（{len(edges)} 条边）")
        print("=" * 60)
        for (s, t, note) in edges:
            print(f"  {s} --{self.rel_name.get(rid, rid)}--> {t}")
            if note:
                print(f"      备注: {note}")
        print("=" * 60)
        return 0

    def search(self, kw):
        kw_l = kw.lower()
        hits = []
        for nid, n in self.nodes.items():
            if kw_l in nid.lower() or kw_l in (n["name"] or "").lower():
                hits.append((nid, n))
        print("=" * 60)
        print(f"🔍 关键词搜索: \"{kw}\"（命中 {len(hits)} 个）")
        print("=" * 60)
        for nid, n in sorted(hits):
            print(f"  {self.node_label(nid)}")
        print("=" * 60)
        return 0 if hits else 1


def main():
    ap = argparse.ArgumentParser(description="知识图谱查询（纯 Python，不依赖 networkx）")
    ap.add_argument("--root", required=True, help="域根绝对路径")
    ap.add_argument("--stats", action="store_true", help="图统计")
    ap.add_argument("--neighbors", metavar="ENTITY_ID", help="查询实体邻居")
    ap.add_argument("--depth", type=int, default=1, help="邻居深度（默认 1）")
    ap.add_argument("--path", nargs=2, metavar=("SRC", "TGT"), help="两实体间最短路径")
    ap.add_argument("--by-class", metavar="CLASS_ID", help="按类查询实例（如 C4）")
    ap.add_argument("--by-relation", metavar="REL_ID", help="按关系查询边（如 R5）")
    ap.add_argument("--search", metavar="KEYWORD", help="按名称关键词搜索实体")
    args = ap.parse_args()

    domain = resolve_root(args.root)
    g = Graph(domain)

    if args.stats:
        sys.exit(g.stats())
    elif args.neighbors:
        sys.exit(g.neighbors(args.neighbors, args.depth))
    elif args.path:
        sys.exit(g.shortest_path(args.path[0], args.path[1]))
    elif args.by_class:
        sys.exit(g.by_class(args.by_class))
    elif args.by_relation:
        sys.exit(g.by_relation(args.by_relation))
    elif args.search:
        sys.exit(g.search(args.search))
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
