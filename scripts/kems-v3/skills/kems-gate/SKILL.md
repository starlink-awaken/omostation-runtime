---
name: kems-gate
description: 任务门禁管道（管道4）。机器捕获时限（月报20日/评分月底）、阻塞（⛔里程碑）、门禁契约（done必须核查交付物）——解决"流程冗长多要求、AI执行总有遗漏"与"靠人记住才没漏"的机制债。
---

# kems-gate — 任务门禁

## 触发
每日巡检 / 事件卡任务推进 / 用户问"有什么快到期/逾期/阻塞"。

## 执行
```bash
python ~/Workspace/projects/runtime/scripts/kems-v3/kems-gate.py [--asof YYYY-MM-DD] [--neg]
```

## 行为
1. 时限面：月报报送（10-20）+ 收入评分（10-31）→ 倒计时/未到期/即将到期/已逾期
2. 阻塞面：key-milestones severity=⛔ → 阻塞清单（M04b/M05/M05b）
3. 门禁面：任务 done 无 checked_deliverables → 违规（P-C7）
4. 记录：`~/.kems-pilot/evidence/gate-<asof>.json`

## 验收
- asof=2026-10-08 → OK（无逾期）；asof=2026-10-25 演练 → ALERT（月报逾期）
- `--neg` → ALERT（虚构逾期+门禁失守必须报）

## 铁律
时限由机器捕获（Deadline/ProjectTask 本体数据），不再靠人记住。
