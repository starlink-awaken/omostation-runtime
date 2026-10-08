---
name: kems-artifact
description: 产物契约管道（管道3）。文档/报告生成与落盘前校验：格式要求、落点目录、命名规范——解决"文档生成位置随机、格式不合规"。
---

# kems-artifact — 产物契约

## 触发
AI 或流程准备生成月报/简报/报告等产物时（生成前先过契约）。

## 执行
```bash
python ~/Workspace/projects/runtime/scripts/kems-v3/kems-artifact.py \
  --check <交付物ID> --name <YYYY-MM-DD-名称.md> --path <产物路径> \
  --format-req <格式要求> --destination <落点> [--neg]
```

## 行为
1. format_req 非空（契约有格式要求）
2. destination 非空且目录存在（落点契约化，杜绝随机落盘）
3. 命名以 YYYY-MM-DD 开头
4. 违规 → REJECT；记录 `~/.kems-pilot/evidence/artifact-<id>.json`

## 验收
- 正样本 → OK；`--neg`（缺格式/乱命名/落点不存在）→ REJECT

## 契约源
Deliverable M2（P1）：`format_req`/`destination` 字段即契约载体。
