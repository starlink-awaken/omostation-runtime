# kems-v2（Workspace 原生重建）

> 重建债 D-8 的落地面。v2.1.1 已随 #2596 事故字节级丢失（9/12 脚本），
> 本目录是 v2.2.0 新版本语义重建：git 托管 + 远端，无 Documents 路径依赖。

## 资产状态

| 脚本 | 状态 | 来源 |
|------|------|------|
| gen-report-view.py | ✅ 字节级抢救 | transcript Write 记录（4170B）|
| kems-cross-check.py | ✅ 字节级抢救 | transcript Write 记录（4180B）|
| kems-toolkit.py | ✅ 字节级抢救 | session outputs 最新副本（7670B，统一版）|
| 9 个（check-* / graph-query / kems-init / kems-snapshot / model-ask / refresh-indexes）| ⏳ 按 v2.1.1 CHANGELOG 蓝本待重写 | 随真实需求推进 |

## 用法（kems-toolkit 统一入口）

```bash
python3 scripts/kems-v2/kems-toolkit.py --root <域根> [--mode check|health] [--dry-run]
```

--root 参数化（不再 symlink 到 Documents），任意 KEMS 文档域通用。
