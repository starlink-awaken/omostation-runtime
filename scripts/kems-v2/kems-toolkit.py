#!/usr/bin/env python3
"""
kems-toolkit.py — KEMS 域工具集（统一版）

供所有 KEMS 文档域共用。以 --root <域根路径> 参数化，对任意域执行：
  --mode check   强制更新检查（目录 hash 比对 + inbox 待分类检测 + 状态基线）
  --mode health  健康度巡检（老化知识 / inbox 滞留 / 待分类 / 信号统计）

用法：
  python3 kems-toolkit.py --root /path/to/domain
  python3 kems-toolkit.py --root /path/to/domain --mode health
  python3 kems-toolkit.py --root <域根> --mode check --dry-run   # 只读不写状态
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

DRY_RUN = False  # 由 __main__ 依据 --dry-run 设置


def resolve_root(raw):
    """解析域根：支持绝对路径与 ~ 展开；目录必须存在。"""
    p = Path(raw).expanduser().resolve()
    if not p.is_dir():
        sys.exit(f"❌ 域根不存在: {p}")
    return p


def find_inbox(domain):
    """兼容两种 inbox 布局：_storage/01-Inbox（卫健委/国转中心）或 _storage/inbox。"""
    for name in ("01-Inbox", "inbox"):
        p = domain / "_storage" / name
        if p.is_dir():
            return p
    return domain / "_storage" / "01-Inbox"


def _banner(title, domain):
    print("=" * 60)
    print(f"{title}")
    print(f"   域: {domain}")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


# ── W2 覆盖面修复（2026-09-20）：递归 + 不丢点文件 + 纳入盲区目录 + 哈希口径可选 ──
# 契约：检测面必须覆盖全部声明面与事实面；凡排除项必须显式列出且可解释。
# 修掉的四个缺陷（域内登记见 _control/.kems_check_list.md 缺陷 3/4/5）：
#   ① os.listdir 非递归            → 原仅覆盖 4 目录顶层（实测 43/6256 = 0.7%）
#   ② f.startswith(".") 丢弃点文件  → 连"该怎么闭环"的规程件自身都不受检
#   ③ 盲区目录未纳入               → .kems/ 与 _entities/{ontology,models,facts}
#   ④ 只比名+mtime、不比内容        → 改内容而不动 mtime 的编辑不可见（由 content 口径覆盖）
EXCLUDE_NAMES = {".DS_Store", ".vm-test"}
BASELINE_NAME = ".kems_check_state.json"
CONTENT_HASH_MAX_BYTES = 2 * 1024 * 1024  # content 口径下超此体积退化为 大小+mtime

# 哈希口径（由 --hash-mode 设置）：
#   meta    递归 (相对路径, 大小, mtime_ns)   —— 6260 文件约 0.20s，pre-commit 用
#   content 递归 (相对路径, 内容 sha256)      —— 6260 文件约 15.7s，定期/CI 深检用
# 注意：切换口径后首次运行，所有目录都会报"发生变化"（算法变了），属预期。
HASH_MODE = "meta"


def _scan(root):
    """返回 (待哈希文件列表, 被排除文件数)。排除项见 EXCLUDE_NAMES / BASELINE_NAME。
    注：**不要**用 fp.resolve() 逐文件比对——那是每文件一次 syscall，
    实测把 6260 文件的耗时从 ~0.2s 抬到 ~1.6s（8 倍）；基线按名排除已足够。"""
    kept, excluded = [], 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for fn in sorted(filenames):
            if fn in EXCLUDE_NAMES or fn == BASELINE_NAME:
                excluded += 1
                continue
            kept.append(Path(dirpath) / fn)
    return kept, excluded


def _hash_tree(root):
    """递归哈希；返回 (8 位摘要, 进面文件数, 被排除文件数)。进面数即该目录的检测面。"""
    h = hashlib.sha256()
    n = 0
    files, excluded = _scan(root)
    for fp in files:
        try:
            st = fp.stat()
        except OSError:
            continue
        h.update(str(fp.relative_to(root)).encode())
        if HASH_MODE == "content" and st.st_size <= CONTENT_HASH_MAX_BYTES:
            try:
                h.update(hashlib.sha256(fp.read_bytes()).digest())
            except OSError:
                h.update(f"{st.st_size}:{st.st_mtime_ns}".encode())
        else:
            h.update(f"{st.st_size}:{st.st_mtime_ns}".encode())
        n += 1
    return h.hexdigest()[:8], n, excluded


def run_check(domain, state_file, extra_inbox=None):
    inbox = find_inbox(domain)
    paths = {
        "inbox": inbox,
        "knowledge": domain / "_knowledge",
        "entities": domain / "_entities" / "entities",
        # W2：以下为原盲区目录，现纳入检测面
        "ontology": domain / "_entities" / "ontology",
        "models": domain / "_entities" / "models",
        "facts": domain / "_entities" / "facts",
        "control": domain / "_control",
        "kems": domain / ".kems",
    }
    # 额外缓冲区目录必须经 --inbox-extra 显式传入，不使用任何默认跨域路径。
    if extra_inbox:
        ep = Path(extra_inbox).expanduser()
        if ep.is_dir():
            paths["buff_inbox"] = ep

    hashes = {}
    coverage = {}
    excluded = {}
    for name, path in paths.items():
        if path.is_dir():
            try:
                hashes[name], coverage[name], excluded[name] = _hash_tree(path)
            except OSError:
                hashes[name] = "error"
                coverage[name] = 0
                excluded[name] = 0
        else:
            hashes[name] = "not_found"
            coverage[name] = 0
            excluded[name] = 0

    saved = {}
    if state_file.is_file():
        try:
            saved = json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            saved = {}

    changes = []
    for name, h in hashes.items():
        sh = saved.get("hashes", {}).get(name, "")
        if sh and sh != h and h != "not_found":
            changes.append(f"⚠️ {name} 发生变化")

    manifest = inbox / "inbox-manifest.md"
    pending = manifest.read_text().count("📥 待分类") if manifest.is_file() else 0
    if pending:
        changes.append(f"⚠️ inbox-manifest 有 {pending} 条待分类")

    _banner("🔍 KEMS 强制更新检查", domain)
    covered = {k: v for k, v in coverage.items() if v > 0}
    excl = {k: v for k, v in excluded.items() if v > 0}
    print(f"\n📐 本次检测面：{sum(covered.values())} 个文件 / {len(covered)} 个目录（递归·{HASH_MODE} 口径）")
    print(f"   分目录：{covered}")
    print(f"   显式排除：{sum(excl.values())} 个（{'/'.join(sorted(EXCLUDE_NAMES))} + 基线自身）{excl}")
    if not changes and saved.get("last_check"):
        print("\n✅ 系统状态正常，无需更新")
        print(f"   上次检查: {saved['last_check']}")
    else:
        if changes:
            print("\n❗ 检测到以下变化：")
            for c in changes:
                print(f"   {c}")
            print("\n⚠️ 请执行更新：确认变化 → 更新KEMS知识 → 更新signals → 更新实体索引 → 提交记录")
        if not saved.get("last_check"):
            print("\n🆕 首次运行，已建立检查基线")

    if not DRY_RUN:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps(
                {"last_check": datetime.now().isoformat(), "hashes": hashes},
                indent=2,
                ensure_ascii=False,
            )
        )
    print("\n" + "=" * 60)
    return len(changes) > 0


# ── mode: health — 健康度巡检 ──
def run_health(domain):
    now = datetime.now()

    stale = []
    know = domain / "_knowledge"
    if know.is_dir():
        for root, dirs, files in os.walk(know):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                # 目录导航 README.md 为归档目录占位说明，mtime 旧属设计正常，不计入老化知识
                if f.endswith(".md") and f != "README.md":
                    fp = Path(root) / f
                    age = (now - datetime.fromtimestamp(fp.stat().st_mtime)).days
                    if age > 30:
                        stale.append((f, age))

    stale_inbox = []
    inbox = find_inbox(domain)
    if inbox.is_dir():
        for f in inbox.iterdir():
            if f.is_file() and not f.name.startswith("."):
                age = (now - datetime.fromtimestamp(f.stat().st_mtime)).days
                if age > 7:
                    stale_inbox.append((f.name, age))

    manifest = inbox / "inbox-manifest.md"
    pending = manifest.read_text().count("📥 待分类") if manifest.is_file() else 0

    signals_file = domain / "_control" / "signals.md"
    signal_count = 0
    signals_note = ""
    if signals_file.is_file():
        # F12 修复（2026-09-20）：原以子串计数冒充条目计数
        #   content.count("signal-") + content.count("- message:")
        # 实测分解（卫健委域 2026-09-20）：全文子串 123（行首仅 116 ⇒ 正文多计 +7）
        #   + "signal-" 全文 5（原判"死代码恒 0"已不成立——登记该缺陷的散文自己贡献了这 5 处）
        #   = 128，而 yaml 实测真值 122 ⇒ 恒偏高 6，且随正文措辞漂移。
        # 正解：切出 frontmatter 取 len(yaml.safe_load(fm)["signals"])。
        # yaml 延迟导入：.kems/_scripts/kems-check 用系统 python3（已验证不依赖 PyYAML），
        # 顶层 import 会打断启动器；无 PyYAML 时退化为"行首 '- message:' 行数"。
        content = signals_file.read_text()
        m = re.match(r"^---\n(.*?)\n---\n", content, re.S)
        if not m:
            signals_note = "（无 frontmatter，未计数）"
        else:
            fm = m.group(1)
            try:
                import yaml  # noqa: PLC0415 — 延迟导入是刻意的（见上）
            except ImportError:
                yaml = None
            if yaml is not None:
                try:
                    sig = (yaml.safe_load(fm) or {}).get("signals")
                    if isinstance(sig, list):
                        signal_count = len(sig)
                    else:
                        signals_note = "（signals 键非列表，未计数）"
                except Exception:
                    signals_note = "（frontmatter 解析失败，未计数）"
            else:
                signal_count = sum(
                    1 for line in fm.splitlines() if line.lstrip().startswith("- message:")
                )
                signals_note = "（无 PyYAML，退化为行首计数）"

    _banner("🔍 KEMS 知识库健康度巡检", domain)
    total = 0
    if stale:
        print(f"\n⚠️ 老化知识（>30天）：{len(stale)}个")
        for f, age in stale[:5]:
            print(f"   · {f}（{age}天）")
        if len(stale) > 5:
            print(f"   ... 共{len(stale)}个")
        total += len(stale)
    else:
        print("\n✅ 知识库新鲜度正常")

    if stale_inbox:
        print(f"\n⚠️ Inbox滞留（>7天）：{len(stale_inbox)}个")
        for f, age in stale_inbox:
            print(f"   · {f}（{age}天）")
        total += len(stale_inbox)
    else:
        print("\n✅ Inbox处理及时")

    if pending:
        print(f"\n⚠️ 待分类文件：{pending}个")
        total += pending
    else:
        print("\n✅ 无待分类文件")

    print(f"\n📊 活跃信号：{signal_count}个{signals_note}")
    print("\n" + "=" * 60)
    if total == 0:
        print("✅ 知识库健康状况：良好")
    else:
        print(f"⚠️ 共发现 {total} 个问题，建议处理")
        print("   优先：更新老化知识 → 归档inbox → 处理待分类")
    print("=" * 60)
    return total


def main():
    global DRY_RUN, HASH_MODE
    ap = argparse.ArgumentParser(description="KEMS 域工具集（统一版）")
    ap.add_argument("--root", required=True, help="域根绝对路径")
    ap.add_argument("--mode", choices=["check", "health"], default="check")
    ap.add_argument("--inbox-extra", default=None, help="额外检查的缓冲区目录")
    ap.add_argument("--dry-run", action="store_true", help="只读模式，不写状态文件")
    ap.add_argument(
        "--hash-mode",
        choices=["meta", "content"],
        default="meta",
        help="哈希口径：meta=相对路径+大小+mtime_ns（快，适合 pre-commit）；"
             "content=递归内容 sha256（慢，适合定期/CI 深检）",
    )
    args = ap.parse_args()

    DRY_RUN = args.dry_run
    HASH_MODE = args.hash_mode
    domain = resolve_root(args.root)
    state_file = domain / "_control" / ".kems_check_state.json"

    if args.mode == "check":
        sys.exit(1 if run_check(domain, state_file, args.inbox_extra) else 0)
    else:
        sys.exit(1 if run_health(domain) > 0 else 0)


if __name__ == "__main__":
    main()
