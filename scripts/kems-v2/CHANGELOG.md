---
type: ssot
owner: governance-team
last_updated: 2026-09-18
---

# kems-v2 CHANGELOG

## v2.2.0 (2026-08-30, D-8 重建; 2026-09-18 完成)

- **重建语义**：v2.1.1 随 #2596 搬迁后包丢失，9/12 脚本字节级永久丢失（principal 决定放弃 iCloud 追查）。
  v2.2.0 是新版本语义的重建，非字节恢复。
- **抢救资产（字节级）**：
  - gen-report-view.py（4170B，transcript Write 记录提取）
  - kems-cross-check.py（4180B，transcript Write 记录提取）
  - kems-toolkit.py（7670B，session outputs 最新副本，--root 参数化统一版）
- **重写清单（9 个，按 CHANGELOG v2.1.1 蓝本，随真实需求逐个推进）**：
  check-critical-path / check-model-conformance / check-ontology-consistency /
  check-ssot-sync / graph-query / kems-init / kems-snapshot / model-ask / refresh-indexes
- **完成状态（2026-09-18）**：上述 9 个脚本完成 Workspace 语义重建；
  `kems-init` 生成的 facts 索引显式声明 `per_file`，避免空域自检误报；
  `graph-query` 移除某一具体域的 223/36 硬编码规模；
  `kems-cross-check` 改为显式 `--domains`，移除 Documents 默认域与 symlink 要求。
- **验收**：`tests/test_kems_v2_rebuild.py` 用四个临时 Workspace 域执行
  init、check、snapshot、query 和 cross-check 语义测试，全程零 Documents 依赖。
- **设计变更**：不再使用 Documents 四域 symlink 单点（事故根因）；以 --root 参数化
  （kems-toolkit 模式），SSOT git 托管，消费者走 Workspace owner 命令。

## 2026-09-19 · kems-toolkit.py EINTR 加固（不升版本，v2.2.0）

- **背景**：2026-09-19 每日巡检触发时，10/11 域 `_knowledge`/`01-Inbox` 目录内容访问持续
  `InterruptedError [Errno 4]`（scandir 30/30 失败、部分文件 open 无限挂起），无 POSIX 信号来源
  （全信号 handler 探测为空），元数据层（stat/ls -ld）正常 → 判定为 macOS FileProvider/文件系统层
  对特定目录树（`_knowledge` 及部分 `_storage` 子树）的中断，非域数据、非工具逻辑问题。
- **改动**：`kems-toolkit.py` 新增 `_iterdir_retry(path, retries=6)` 与
  `_walk_retry(top, retries=6)`（按目录粒度重试，不重复产出已处理目录），替换 `run_health` 内
  `inbox.iterdir()` 与 `os.walk(know)`。EINTR 为系统调用层瞬态/持续中断时重试吸收，持续失败仍如实抛出。
- **备份**：`kems-toolkit.py.bak-20260919`
- **验证**：`py_compile` 通过；补丁后重跑 11 域——卫健委正常（结果可靠），10 域仍 EINTR
  （持续 30/30 失败）→ 重试无法解决系统层阻塞，结论如实登记快照，待环境恢复复跑。
- **教训**：macOS FileProvider 阻塞时"重试吸收瞬态"与"持续失败"都要可区分；巡检受限时不得伪造健康数据。
