#!/usr/bin/env python3
"""check-model-conformance.py — 模型一致性检查

校验 _entities/models/ 下模型文件：
  1. 每个 .md 有 frontmatter，且含 title/status/type/owner/created 五字段
  2. 模型正文中引用的实体 id（instances.yaml 注册 id）必须存在
  3. 模型正文中引用的关系（relations.yaml 的 code 或 R1-R9）必须存在
统计：模型总数、合规数、不合规清单。

用法：
  python3 check-model-conformance.py --root <域根>
退出码：0=全部合规，1=存在不合规模型。
"""
import argparse
import re
import sys
from pathlib import Path

import yaml

REQUIRED_FIELDS = ["title", "status", "type", "owner", "created"]


def resolve_root(raw):
    p = Path(raw).expanduser().resolve()
    if not p.is_dir():
        sys.exit(f"❌ 域根不存在: {p}")
    return p


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def parse_frontmatter(path):
    """严格解析 frontmatter，返回 (fm_dict, body_text, issue)。

    **严格**的含义：终止符必须是**整行** `---`。
    原实现用 `text.find("\\n---", 3)` 做**前缀匹配**，`\\n------` 也会被命中，
    于是终止符写成 `------` 的文件被截出"正确"的 YAML 而报合规——实测曾使
    9 个非法终止符的模型一并被判 32/32 合规，而严格解析器却读不到它们。
    （失效模式 F9：宽松解析掩盖非法写法 → 检查器与消费者结论相反。）

    issue: None（正常，或无 frontmatter）/ "unclosed" /
           "illegal-terminator:<文本>" / "yaml-error:<msg>" / "yaml-not-mapping"
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text, None
    for i in range(1, len(lines)):
        s = lines[i].strip()
        if s == "---":
            fm_raw = "\n".join(lines[1:i])
            try:
                fm = yaml.safe_load(fm_raw)
            except yaml.YAMLError as e:
                first = str(e).splitlines()[0] if str(e) else "YAMLError"
                return None, text, f"yaml-error:{first[:70]}"
            if fm is None:
                return {}, "\n".join(lines[i + 1:]), None
            if not isinstance(fm, dict):
                return None, text, "yaml-not-mapping"
            return fm, "\n".join(lines[i + 1:]), None
        if len(s) >= 4 and set(s) == {"-"}:
            return None, text, f"illegal-terminator:{s}"
    return None, text, "unclosed"


def main():
    ap = argparse.ArgumentParser(description="模型一致性检查")
    ap.add_argument("--root", required=True, help="域根绝对路径")
    args = ap.parse_args()
    domain = resolve_root(args.root)

    models_dir = domain / "_entities" / "models"
    ont = domain / "_entities" / "ontology"

    print("=" * 60)
    print("🔍 模型一致性检查")
    print(f"   域: {domain}")
    print("=" * 60)

    if not models_dir.is_dir():
        print(f"❌ 模型目录不存在: {models_dir}")
        sys.exit(1)

    # 载入本体
    instances = load_yaml(ont / "instances.yaml")
    relations = load_yaml(ont / "relations.yaml")
    aliases = load_yaml(ont / "aliases.yaml")
    inst_ids = {i.get("id") for i in (instances.get("instances", []) or []) if i.get("id")}
    rel_ids = {r.get("id") for r in (relations.get("relations", []) or []) if r.get("id")}
    rel_codes = {r.get("code") for r in (relations.get("relations", []) or []) if r.get("code")}
    # 已知实体 id = 实例 id ∪ 别名 canonical ∪ 视图 id（视图不设实例但已登记）
    known_ids = set(inst_ids)
    for a in (aliases.get("aliases", []) or []):
        if a.get("canonical"):
            known_ids.add(a["canonical"])
        if a.get("alias"):
            known_ids.add(a["alias"])
    for v in (aliases.get("views", []) or []):
        if v.get("id"):
            known_ids.add(v["id"])

    model_files = sorted(models_dir.glob("*.md"))
    total = len(model_files)
    compliant = 0
    noncompliant = []

    print(f"\n模型文件总数: {total}")
    print("-" * 60)

    for mf in model_files:
        fm, body, issue = parse_frontmatter(mf)
        problems = []

        # 1. frontmatter 结构（可解析性）+ 必备字段
        if issue == "unclosed":
            problems.append("frontmatter 未闭合（缺整行 `---`）")
        elif issue and issue.startswith("illegal-terminator:"):
            problems.append(
                f"非法 frontmatter 终止符 {issue.split(':', 1)[1]}"
                "（必须恰为整行 `---`；否则严格解析器读不到本文件）"
            )
        elif issue and issue.startswith("yaml-error:"):
            problems.append(f"frontmatter YAML 不可解析：{issue.split(':', 1)[1]}")
        elif issue == "yaml-not-mapping":
            problems.append("frontmatter 不是键值映射")
        elif fm is None:
            problems.append("缺少 frontmatter")
        else:
            for fld in REQUIRED_FIELDS:
                if fld not in fm or not fm[fld]:
                    problems.append(f"frontmatter 缺字段: {fld}")

        # 2. 正文中引用的实体 id 是否存在
        # 扫描 body 中疑似实体 token（pol-/org-/proj-/sys-/dat-/inf-/person- 等前缀），
        # 凡匹配到的 token 必须已登记（实例或别名/视图）
        missing_entities = set()
        tokens = set(re.findall(r"\b(?:pol|org|proj|sys|dat|inf|person|evt|doc|finance|diagnostic|model|domain)-[a-z0-9][a-z0-9\-]*", body))
        for tok in tokens:
            if tok not in known_ids:
                missing_entities.add(tok)

        # 3. 关系引用（R1-R9 或 code）
        missing_relations = set()
        r_tokens = set(re.findall(r"\bR[1-9]\b", body))
        for rt in r_tokens:
            if rt not in rel_ids:
                missing_relations.add(rt)
        # code 引用（bases_on/governs/implements/deploys/data_flows 等）
        known_codes = rel_codes
        for code in known_codes:
            if code and re.search(r"\b" + re.escape(code) + r"\b", body):
                if code not in rel_codes:
                    missing_relations.add(code)

        if problems:
            for p in problems:
                print(f"❌ {mf.name}: {p}")
            noncompliant.append((mf.name, problems))
        else:
            print(f"✅ {mf.name}")
            compliant += 1

        if missing_entities:
            for me in sorted(missing_entities):
                print(f"   ⚠️ {mf.name}: 引用实体 id 未注册: {me}")
        if missing_relations:
            for mr in sorted(missing_relations):
                print(f"   ⚠️ {mf.name}: 引用关系未定义: {mr}")

    print("\n" + "=" * 60)
    print(f"📊 模型总数: {total}, 合规: {compliant}, 不合规: {len(noncompliant)}")
    if noncompliant:
        print("不合规清单:")
        for name, probs in noncompliant:
            print(f"   · {name}: {'; '.join(probs)}")
    print("=" * 60)
    sys.exit(1 if noncompliant else 0)


if __name__ == "__main__":
    main()
