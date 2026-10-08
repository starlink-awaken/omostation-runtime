---
name: kems-intake
description: 进料自动索引管道（管道1）。新文件进库时校验 frontmatter、挂载本体候选（项目/环节/依据/事件）、生成索引记录——解决"新文件不自动索引、不挂时间线/事件线、关联资料易遗漏"。
---

# kems-intake — 进料自动索引

## 触发
新文件入库（Inbox/下载/邮件附件落盘）或用户说"这个文件帮我挂到知识库里"。

## 执行
```bash
python ~/Workspace/projects/runtime/scripts/kems-v3/kems-intake.py <文件路径> [--neg]
```

## 行为
1. frontmatter 检查：`title/date/status/owner` 缺失 → 索引缺口（FAIL）
2. 本体挂载：文件名+内容命中词表 → 候选实体 id（ProjectPilot/WorkflowStage/Requirement/PilotEvent/Deadline）
3. 记录：`~/.kems-pilot/evidence/intake-<basename>.json`

## 验收
- 正样本（有 frontmatter 的真实文件）→ PASS 且挂载候选非空
- `--neg`（剥离 frontmatter）→ FAIL

## 下沉标准
实现驻留执行面 kems-v3；域内零实现，只留数据/证据。
