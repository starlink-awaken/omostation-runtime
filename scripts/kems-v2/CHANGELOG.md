# kems-v2 CHANGELOG

## v2.2.0 (2026-08-30, D-8 重建)

- **重建语义**：v2.1.1 随 #2596 搬迁后包丢失，9/12 脚本字节级永久丢失（principal 决定放弃 iCloud 追查）。
  v2.2.0 是新版本语义的重建，非字节恢复。
- **抢救资产（字节级）**：
  - gen-report-view.py（4170B，transcript Write 记录提取）
  - kems-cross-check.py（4180B，transcript Write 记录提取）
  - kems-toolkit.py（7670B，session outputs 最新副本，--root 参数化统一版）
- **重写清单（9 个，按 CHANGELOG v2.1.1 蓝本，随真实需求逐个推进）**：
  check-critical-path / check-model-conformance / check-ontology-consistency /
  check-ssot-sync / graph-query / kems-init / kems-snapshot / model-ask / refresh-indexes
- **设计变更**：不再使用 Documents 四域 symlink 单点（事故根因）；以 --root 参数化
  （kems-toolkit 模式），SSOT git 托管，消费者走 Workspace owner 命令。
