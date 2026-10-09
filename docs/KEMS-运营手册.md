---
title: KEMS 运营手册（v1）
date: 2026-10-09
status: active
owner: 夏明星
type: handbook
tags: [KEMS, 运营, 手册, 运维]
---

# KEMS 运营手册（v1，2026-10-09）

> 收敛 P0-P4 试点、全域推广、可遵循性三轮工作的运营知识。运行时以本手册为准，
> 实现全部驻留执行面 `~/Workspace/projects/runtime/scripts/kems-v3/`。

## 1. 体系架构（三层）
| 层 | 内容 | 位置 |
|---|---|---|
| 元模型层（MOF） | M2 通用域本体（kems-pilot 类型集）+ M1 全域声明 | `~/Workspace/projects/ecos/src/ecos/ssot/mof/` |
| 数据层 | 12 域本体数据（97 实例）+ 语料元数据 | `~/.kems-pilot/domains/<id>/instances.yaml` |
| 执行层 | 四管道 CLI×9 + SKILL.md×5 + MCP 读面桥 | `~/Workspace/projects/runtime/scripts/kems-v3/` |
| 治理层 | 域清单 SSOT + 可遵循性声明 | `@公共/_control/L4-DOMAIN-REGISTRY.yaml`、`KEMS-FOLLOWABILITY.yaml` |

## 2. 运行机制（四管道，程序为核心）
| 管道 | 命令 | 治理问题 |
|---|---|---|
| 1 进料 | `kems-intake.py <文件> --domain <id>` | 新文件不索引/关联漏 |
| 2 融合 | `kems-fusion.py --domain <id>` | 多源口径冲突不暴露 |
| 3 产物 | `kems-artifact.py --check D --name 2026-.. --path ..` | 产物乱放/格式不合规 |
| 4 门禁 | `kems-gate.py --domain <id> --asof <日>` | 时限靠人记、多要求总有遗漏 |

**黄金规则**：每次验证带负对照（`--neg`）；判定全部确定性代码；证据留痕 `~/.kems-pilot/evidence/`。

## 3. 事件日历（机器捕获时限）
| 日期 | 事件 | 动作 |
|---|---|---|
| 每域 20 日前 | 月度报送类硬时限 | gate 巡检（10-20 月报门禁已设定时任务 08:30 自动触发） |
| 每域 月底 | 评分/收口类时限 | gate --asof 月底演算 |
| 阻塞面 | ⛔ 里程碑（如 M04b/M05/M05b 经信局批复未出） | gate 输出 blocked_milestones，人工推进前置 |

## 4. 验收口径（S 系列 + 可遵循性）
- 覆盖矩阵：12 域 0 违规；蒸馏源=真实文件，源标注
- 四管道：正负对照全过（intake frontmatter、fusion 冲突暴露、artifact 契约、gate 逾期）
- 可遵循性 R1-R8（kems-follow.py）：事实可溯≥90%、先影子、数字可复算、冲突必暴露、负对照必跑、产物契约、不伪装全绿、授权边界审计
- 使用证据 S9：近 2 周 ≥5 个真实任务主动经管道
- 冷启动 S8：新会话仅凭模型数据答 3 问（协议 kems-s8-coldstart.py，10-20 定时任务中终验）

## 5. 运维命令速查
```bash
PY=~/Workspace/projects/ecos/.venv/bin/python
KEMS=~/Workspace/projects/runtime/scripts/kems-v3
$PY $KEMS/kems-domain-matrix.py --deep creative,opc,cockpit   # 重算覆盖矩阵
$PY $KEMS/kems-pipe-accept.py                                  # 12 域四管道验收
$PY $KEMS/kems-follow.py                                       # 可遵循性 R1-R8
$PY $KEMS/kems-gate.py --domain work-weijian --asof 2026-10-20 # 门禁演算
$PY $KEMS/kems-frontmatter.py --domain all --apply             # 治理补全（先 dry-run）
$PY $KEMS/kems-aggregate.py --domain work-docs --sub work-weijian,work-guozhuan,work-liyongke,work-contracts  # 聚合域投影（负对照不落盘）
```
MCP 读面：`http://127.0.0.1:7431/mcp`（launchd 常驻，25 工具，含 domains_matrix/pipeline_status）。

## 6. 治理边界与已知限制（如实）
- **聚合域**：@工作文档（work-docs）已补齐子域聚合投影（用户 2026-10-09 拍板）——由 kems-aggregate.py 聚合 4 子域实例（32 条，每条标注 source_domain），matrix 对聚合域只读不覆盖；语料元数据 733 文件/3.7M 在 _domain_meta.extraction
- **未授权动作**：系统级变更（除本机 LaunchAgent）不主动做；cron 定时任务需用户明确推进
- **独立会话**：S8 终验须在无试点历史的新会话执行（10-20 定时任务会话满足条件）
- **work-guozhuan 里程碑**：key-milestones 数据为空（控制面已接入，填写后矩阵自动加深）

## 7. 迭代纪律
- 每轮推进：探查→约束→证据→执行→验证→交付；改域内文件先备份；实现只进执行面
- 提交：runtime/ecos 子模块 commit+push main（仅预期路径，R8 自动审计）
- 本手册本身遵守 R7（不伪装全绿：已知限制如实列出）
