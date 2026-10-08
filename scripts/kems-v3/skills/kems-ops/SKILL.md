---
name: kems-ops
description: KEMS 运维工具组入口——覆盖矩阵、全域验收、frontmatter 治理、可遵循性校验、读面状态。当需要巡检 KEMS 体系状态、重算 12 域覆盖矩阵、跑四管道全域验收、补全控制文件元数据、或核对 agent 可遵循性（R1-R8）时使用。
---

# KEMS Ops — 运维工具组 SKILL

## 触发场景
- 「看看 KEMS 体系现在什么状态 / 巡检」
- 「重新算一遍 12 域覆盖矩阵 / 验收四管道」
- 「补全控制文件 frontmatter / intake 为什么 FAIL」
- 「检查 agent 是否可遵循（可遵循性 / R 规则）」
- 任何读面（矩阵/管道状态）或治理动作

## 环境
- 解释器：`/Users/xiamingxing/Workspace/projects/ecos/.venv/bin/python`（系统 python3 无 yaml，已证死）
- 工具目录：`/Users/xiamingxing/Workspace/projects/runtime/scripts/kems-v3/`
- 数据/证据：`~/.kems-pilot/`（沙箱、domains、evidence）
- 域发现源：`@公共/_control/L4-DOMAIN-REGISTRY.yaml`（SSOT，12 域唯一真源，不手抄）

## 工具清单（全部驻留执行面，域内零实现）
| 工具 | 用途 | 关键参数 |
|---|---|---|
| kems-domain-matrix.py | 12 域覆盖矩阵（探测+蒸馏+校验） | `--deep <id,id>`（里程碑上限 20） |
| kems-pipe-accept.py | 12 域四管道验收（intake/fusion±/artifact±/gate） | 无参，读 registry |
| kems-frontmatter.py | 控制文件元数据补全治理 | `--domain <id\|all>` `--apply`（默认 dry-run） |
| kems-follow.py | agent 可遵循性校验（R1-R8） | 无参 |
| kems-status.py | 试点域四管道状态聚合 | `--raw` |
| kems-gate.py | 任务门禁（时限/阻塞/门禁面） | `--domain <id>` `--asof YYYY-MM-DD` `--neg` |
| kems-intake.py | 进料索引（frontmatter+本体挂载） | `<文件>` `--domain <id>` `--neg` |
| kems-fusion.py | 多源融合（冲突暴露+SSOT 裁决） | `--domain <id>` `--neg` |
| kems-artifact.py | 产物契约（格式/落点/命名） | `--check/--name/--path` `--domain` `--neg` |
| mcp-cockpit-http.py | MCP 读面桥（launchd 常驻，端口 7431） | 工具：domains_matrix/pipeline_status/kems_status 等 |

## 验收口径（正负对照，必须跑）
- 覆盖矩阵：每域 0 违规才 OK；蒸馏源=真实文件（key-milestones/项目口径/STATUS/TIMELINE），源文件标注
- 四管道：intake 正=有 frontmatter PASS；fusion 负对照=异值必暴露；artifact 负对照=缺契约必 REJECT；gate ALERT=真实逾期信号（非失败）
- 可遵循性：R1-R8 全 PASS（R1 可溯率≥90%、R2 沙箱+备份、R5 负对照记录、R8 提交范围+域内零实现）

## 下沉纪律（补丁+证据）
- 实现只进 kems-v3；域内只留数据/声明/证据；改域内文件先备份（.bak-YYYYMMDD）
- 每次运行写 evidence JSON（可复算）；不伪装全绿（degraded/待办如实）
- 子模块提交：runtime/ecos 各自 commit+push main（仅预期路径）

## 已知限制（如实）
- work-docs 为聚合域（子域控制面在各子域 _control），无独立业务控制面 → 实例 0，语料元数据在 _domain_meta.extraction
- MCP 桥由 launchd 常驻（com.kems.cockpit-mcp），日志 /tmp/kems-mcp-launchd*.log
- 10-20 月报门禁：定时任务「十月月报门禁巡检与S8终验」（at 2026-10-20 08:30）自动触发
