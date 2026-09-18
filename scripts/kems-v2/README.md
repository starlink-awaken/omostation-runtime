---
type: derived
source: projects/runtime
owner: governance-team
last_updated: 2026-09-18
---

# kems-v2（Workspace 原生重建）

> D-8 的 Workspace 原生重建。v2.1.1 已随 #2596 事故字节级丢失（9/12 脚本），
> v2.2.0 是新版本语义重建：12 个工具全部由 git 托管 + 远端，无 Documents 路径依赖。

## 资产状态

| 脚本 | 状态 | 来源 |
|------|------|------|
| gen-report-view.py | ✅ 字节级抢救 | transcript Write 记录（4170B）|
| kems-cross-check.py | ✅ v2.2.0 语义重写 | 显式 `--domains`，无 Documents 默认值 |
| kems-toolkit.py | ✅ 字节级抢救 | session outputs 最新副本（7670B，统一版）|
| 9 个（check-* / graph-query / kems-init / kems-snapshot / model-ask / refresh-indexes）| ✅ v2.2.0 语义重建 | 纯文本/本地域语义，无外部运行态 |
| VERSION | ✅ v2.2.0 | D-8 重建版本标记 |

## 用法（kems-toolkit 统一入口）

```bash
python3 scripts/kems-v2/kems-toolkit.py --root <域根> [--mode check|health] [--dry-run]
```

跨域巡检只接受显式 Workspace 域根：

```bash
python3 scripts/kems-v2/kems-cross-check.py --domains <域根A>,<域根B>
```

`--root` 参数化（不再 symlink 到 Documents），任意 KEMS 文档域通用。
