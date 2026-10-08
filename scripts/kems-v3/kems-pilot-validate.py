#!/usr/bin/env python3
"""kems-pilot-validate.py — P1 本体蒸馏校验（kems-pilot 试点）。

归属（L4 三面标准）：实现驻留执行面（Workspace/kems-v3）；数据源=沙箱副本
（~/.kems-pilot/卫健委-shadow/）；校验器=MOF Compiler 生成的 Pydantic 模型
（ecos/src/ecos/ssot/mof/generated/kems-pilot/mof_control_models.py）。

模式：
  正样本 = 从真实文件蒸馏的实例（key-milestones.yaml 动态读取 + 蒸馏夹具）；
  负对照 = 故意违规实例（⛔ 无阻塞原因、done 无交付物）——必须被校验器拒绝，
  否则说明校验器形同虚设（负对照失败即 P1 失败）。

输出：~/.kems-pilot/evidence/2026-10-08-p1-validation.json（机器可读证据）。
"""
from __future__ import annotations

import json
import sys
import pathlib

sys.path.append("/Users/xiamingxing/Workspace/projects/ecos/src/ecos/ssot/mof/generated/kems-pilot")

import yaml  # noqa: E402
from mof_control_models import (  # noqa: E402
    Caliber,
    Deadline,
    Deliverable,
    Milestone,
    OrgPilot,
    PilotEvent,
    ProjectPilot,
    ProjectTask,
    Requirement,
    WorkflowStage,
)

SBOX = pathlib.Path.home() / ".kems-pilot/卫健委-shadow"
EVIDENCE_DIR = pathlib.Path.home() / ".kems-pilot/evidence"
EVIDENCE_PATH = EVIDENCE_DIR / "2026-10-08-p1-validation.json"

# ⛔ 节点阻塞原因/影响（蒸馏自 key-milestones.yaml 各节点 note，2026-09-17/18 记录）
BLOCKED_NOTE = {
    "M04b": ("前置依赖 M04 经信局批复未出", "财政评审申报无法推进"),
    "M05": ("经信局审批环节卡点，领导已去协调（外部动作进行中）", "初设报送/后续流程阻塞，材料已齐备非文档缺口"),
    "M05b": ("需等经信局审批完成后发布（前置依赖明确）", "采购意向公开延后，正式公开版已齐备"),
}

results: dict = {"summary": {}, "by_type": {}, "instances": [], "negative_controls": []}


def record(model: str, ok: bool, name: str, detail: str) -> None:
    results["instances"].append(
        {"model": model, "ok": ok, "name": name, "detail": detail[:200]}
    )


def validate(model_cls, payload, name: str) -> None:
    # 第 1 层：生成模型结构校验（类型/枚举/闭式映射/条件约束）
    try:
        obj = model_cls(**payload)
    except Exception as exc:  # pydantic.ValidationError
        record(model_cls.__name__, False, name, f"结构拒绝: {str(exc)[:160]}")
        return
    # 第 2 层：规则表（与 M2 validationRules 同源；编译器发射器 v1.x 尚不发射规则，
    # 故由校验器规则层承担，P3 门禁引擎将接管为唯一执行点）
    for rule_name, check in PILOT_RULES.get(model_cls.__name__, []):
        if not check(obj):
            record(model_cls.__name__, False, name, f"规则拒绝: {rule_name}")
            return
    record(model_cls.__name__, True, name, "通过")


# 试点规则表（P-C4 结构层由生成模型条件约束承担；语义层与 P-C5/P-C7 在此执行）
PILOT_RULES = {
    "Milestone": [
        ("severity 以状态标记开头（✅/🟡/⛔/⚠️/❌，可带语义后缀如 ⛔阻塞）",
         lambda m: m.severity.startswith(("✅", "🟡", "⛔", "⚠️", "❌"))),
        ("severity=⛔ 必须声明阻塞原因与影响（P-C4，兼容后缀形态）",
         lambda m: not m.severity.startswith("⛔") or (m.blocked_reason and m.impact)),
    ],
    "ProjectTask": [
        ("任务置 done 前必须核查交付物（P-C7 门禁契约）", lambda t: t.status != "done" or (t.checked_deliverables and len(t.checked_deliverables) > 0)),
    ],
    "Deadline": [
        ("剩余天数不得为负（逾期转状态而非负值）", lambda d: d.days_left is None or d.days_left >= 0),
    ],
}


def main() -> int:
    # ── 1. 正样本：key-milestones.yaml（动态读取 9 节点） ──
    km_path = SBOX / "_control/key-milestones.yaml"
    km = yaml.safe_load(km_path.read_text(encoding="utf-8"))
    for m in km["milestones"]:
        payload = {
            "id": m["id"],
            "date": m["date"],
            "title": m["title"],
            "severity": m["severity"],
            "owner": m["owner"],
            "gap_ids": m.get("gap_ids") or [],
            "req_files": m.get("req_files") or [],
            "note": m.get("note", ""),
        }
        if str(m["severity"]).startswith("⛔") and m["id"] in BLOCKED_NOTE:
            payload["blocked_reason"], payload["impact"] = BLOCKED_NOTE[m["id"]]
        validate(Milestone, payload, f"milestone-{m['id']}")

    # ── 2. 正样本：项目口径.yaml → ProjectPilot + Caliber ──
    cal_path = SBOX / "_control/项目口径.yaml"
    cal = yaml.safe_load(cal_path.read_text(encoding="utf-8"))
    project = {
        "id": "proj-data-collect",
        "full_name": cal["口径"]["项目全称"],
        "nature": cal["口径"]["项目性质"],
        "investment_wan": float(cal["口径"]["总投资万元"]),
        "software_fee_wan": float(cal["口径"]["软件开发费万元"]),
        "supervision_fee_wan": float(cal["口径"]["监理费万元"]),
        "funding_source": cal["口径"]["资金来源"],
        "institution_count": 33,
        "build_period": cal["口径"]["建设周期"],
        "owner": cal["口径"]["项目负责人"],
        "contact": cal["口径"]["联络人"],
        "supervising_leader": cal["口径"]["主管领导"],
        "parent_project": cal["口径"]["项目归属"],
        "deployment": cal["口径"]["部署环境"],
        "data_scope": cal["口径"]["数据范围"],
        "status": "经信局审核",  # key-milestones M04 note: 项目目前仍在经信局环节
        "performance_indicators": {
            "数量": {"items": cal["绩效指标"]["数量"]},
            "质量": {"items": cal["绩效指标"]["质量"]},
            "进度": {"items": cal["绩效指标"]["进度"]},
            "成本": {"items": cal["绩效指标"]["成本"]},
            "效果": {"items": cal["绩效指标"]["效果"]},
        },
    }
    validate(ProjectPilot, project, "proj-data-collect（口径 SSOT 蒸馏）")
    for key, value in cal["口径"].items():
        if key in ("项目性质", "项目负责人", "联络人", "主管领导"):
            continue  # 已入 ProjectPilot 结构化字段，避免重复
        validate(
            Caliber,
            {
                "id": f"cal-{key}",
                "key": key,
                "value": str(value),
                "project": "proj-data-collect",
                "source_file": str(cal_path),
                "confirm_method": "文件",
            },
            f"caliber-{key}",
        )

    # ── 3. 正样本：蒸馏夹具（申报清单 7 环节 → Stage/Deliverable/Requirement） ──
    stages = [
        {"id": "STG-01", "seq": 1, "name": "内部决策与准备",
         "work_content": "单位集体研究，形成申报事项和资金安排意见",
         "formed_materials": ["DEL-MEETING-MINUTES"], "basis_materials": ["REQ-DANGWEI-RECORD"],
         "approver": "org-fsqwsj", "status": "完成"},
        {"id": "STG-02", "seq": 2, "name": "编制申报材料",
         "work_content": "编制申报表、建设方案，测算预算",
         "formed_materials": ["DEL-APPLY-FORM", "DEL-PLAN"], "basis_materials": ["REQ-POLICY-BASIS"],
         "approver": "org-fsqwsj", "status": "完成"},
        {"id": "STG-03", "seq": 3, "name": "专家论证（按需）",
         "work_content": "组织专家对建设方案、投资估算进行论证",
         "formed_materials": ["DEL-EXPERT-OPINION"], "basis_materials": ["REQ-EXPERT-SIGNIN"],
         "approver": "org-fsqwsj", "status": "完成"},
        {"id": "STG-04", "seq": 4, "name": "经信局审核",
         "work_content": "向区经济和信息化局致函申请审核，随函附申报材料",
         "formed_materials": ["DEL-APPLY-LETTER", "DEL-APPLY-FORM", "DEL-PLAN", "DEL-EXPERT-OPINION"],
         "basis_materials": ["REQ-JXJ-OPINION"], "approver": "org-jxj", "status": "阻塞"},
        {"id": "STG-05", "seq": 5, "name": "申请资金",
         "work_content": "经信局审核同意后，向区政府请示拨付项目建设资金",
         "formed_materials": ["DEL-FUND-REQ"], "basis_materials": ["REQ-JXJ-OPINION", "REQ-LEADER-OPINION"],
         "approver": "org-fsqwsj", "status": "未开始"},
        {"id": "STG-06", "seq": 6, "name": "财政评审",
         "work_content": "按财政评审要求报送预算材料，开展预算评审",
         "formed_materials": ["DEL-FSR", "DEL-REVIEW-DETAIL", "DEL-QUOTE", "DEL-PLAN"],
         "basis_materials": ["REQ-JXJ-OPINION", "REQ-LEADER-OPINION"],
         "approver": "org-czj", "status": "阻塞"},
        {"id": "STG-07", "seq": 7, "name": "政府采购",
         "work_content": "按评审后金额组织政府采购、签订合同",
         "formed_materials": ["DEL-BUDGET-APPROVAL", "DEL-PURCHASE-CONTRACT"],
         "basis_materials": ["REQ-BUDGET-REPLY"], "approver": "org-fsqwsj", "status": "未开始"},
    ]
    for s in stages:
        validate(WorkflowStage, s, f"stage-{s['id']}")

    deliverables = [
        {"id": "DEL-MEETING-MINUTES", "name": "三重一大集体决策会议纪要", "deliverable_type": "报告", "stage": "STG-01", "approval_status": "已备案"},
        {"id": "DEL-APPLY-FORM", "name": "信息化建设项目申报表", "deliverable_type": "申报表", "stage": "STG-02", "approval_status": "已报送"},
        {"id": "DEL-PLAN", "name": "建设方案", "deliverable_type": "建设方案", "stage": "STG-02", "approval_status": "已报送"},
        {"id": "DEL-EXPERT-OPINION", "name": "专家论证意见", "deliverable_type": "论证意见", "stage": "STG-03", "approval_status": "已备案"},
        {"id": "DEL-APPLY-LETTER", "name": "申报函", "deliverable_type": "申报函", "stage": "STG-04", "approval_status": "已报送"},
        {"id": "DEL-FUND-REQ", "name": "资金请示（京房卫请）", "deliverable_type": "资金请示", "stage": "STG-05", "approval_status": "待审批"},
        {"id": "DEL-FSR", "name": "可研报告", "deliverable_type": "报告", "stage": "STG-06", "approval_status": "待审批"},
        {"id": "DEL-REVIEW-DETAIL", "name": "评审明细表", "deliverable_type": "评审材料", "stage": "STG-06", "approval_status": "待审批"},
        {"id": "DEL-QUOTE", "name": "三方报价", "deliverable_type": "清单", "stage": "STG-06", "approval_status": "待审批"},
        {"id": "DEL-BUDGET-APPROVAL", "name": "预算批复", "deliverable_type": "批复", "stage": "STG-07", "approval_status": "待审批"},
        {"id": "DEL-PURCHASE-CONTRACT", "name": "采购合同", "deliverable_type": "合同", "stage": "STG-07", "approval_status": "未要求"},
        {"id": "DEL-MONTHLY-REPORT", "name": "月度工作月报", "deliverable_type": "月报", "stage": "STG-02", "approval_status": "待审批", "format_req": "口径 SSOT 对照，20 日报送", "destination": "月报落点由 P3 artifact-contract 固定"},
    ]
    for d in deliverables:
        validate(Deliverable, d, f"deliverable-{d['id']}")

    requirements = [
        {"id": "REQ-DANGWEI-RECORD", "name": "党委会（办公会）记录", "level": "委内", "field": "卫生"},
        {"id": "REQ-POLICY-BASIS", "name": "政策文件依据", "level": "市级", "field": "采购"},
        {"id": "REQ-EXPERT-SIGNIN", "name": "专家签到表", "level": "委内", "field": "卫生"},
        {"id": "REQ-JXJ-OPINION", "name": "经信局审核意见（函）", "level": "区级", "field": "采购",
         "requirement_text": "财政评审必备依据之一；评审以经信局审核金额、区财政局审核金额为准", "source_org": "org-jxj"},
        {"id": "REQ-LEADER-OPINION", "name": "区领导批示", "level": "区级", "field": "采购", "source_org": "org-fsqwsj"},
        {"id": "REQ-BUDGET-REPLY", "name": "预算批复", "level": "区级", "field": "财政", "source_org": "org-czj"},
    ]
    for r in requirements:
        validate(Requirement, r, f"requirement-{r['id']}")

    # ── 4. 正样本：事件/任务/时限/组织（事件卡 + key-milestones 蒸馏） ──
    events = [
        {"id": "EVT-20260917-FAMDOC-VETO", "name": "家医健康管理中心被市卫健委否决", "event_type": "决策",
         "occurred_date": "2026-09-17", "severity": "阻塞",
         "source_ref": "_control/key-milestones.yaml 文件头注记",
         "caliber_delta": "家医原 544 万区级立项路径否决，改建家医健康服务实施项目承接统建成果"},
        {"id": "EVT-20260929-DAXING-BID", "name": "大兴区基层卫生健康数智化能力提升项目开标", "event_type": "时点",
         "occurred_date": "2026-09-29", "severity": "告警",
         "source_ref": "_control/key-milestones.yaml M07 note",
         "caliber_delta": "统建区共用大兴招标结果，房山新路径启动前提"},
        {"id": "EVT-20260716-JY-144", "name": "市政府纪要144号：三医数据集中接入共管共用", "event_type": "信号",
         "occurred_date": "2026-07-16", "severity": "信息",
         "source_ref": "2026-08-05-144号对三新建项目影响评估.md"},
        {"id": "EVT-202610-MONTHLY-ANCHOR", "name": "十月月报闭环锚定（试点事件）", "event_type": "时点",
         "severity": "提醒",
         "source_ref": "@公共/_storage/05-交付区/06-KEMS知识工程/2026-10-08-事件卡-十月月报闭环.md"},
    ]
    for e in events:
        validate(PilotEvent, e, f"event-{e['id']}")

    tasks = [
        {"id": "TSK-2026-10-MONTHLY-01", "name": "十月月报-数据采集", "task_type": "数据采集", "event": "EVT-202610-MONTHLY-ANCHOR", "status": "pending"},
        {"id": "TSK-2026-10-MONTHLY-02", "name": "十月月报-融合裁决", "task_type": "融合裁决", "event": "EVT-202610-MONTHLY-ANCHOR", "status": "pending"},
        {"id": "TSK-2026-10-MONTHLY-03", "name": "十月月报-撰写", "task_type": "撰写", "event": "EVT-202610-MONTHLY-ANCHOR", "status": "pending"},
        {"id": "TSK-2026-10-MONTHLY-04", "name": "十月月报-门禁核查", "task_type": "门禁核查", "event": "EVT-202610-MONTHLY-ANCHOR",
         "checked_deliverables": ["DEL-MONTHLY-REPORT"], "status": "pending"},
        {"id": "TSK-2026-10-MONTHLY-05", "name": "十月月报-报送", "task_type": "报送", "event": "EVT-202610-MONTHLY-ANCHOR",
         "deadline": "DL-M06-202610", "status": "pending"},
        {"id": "TSK-2026-10-MONTHLY-06", "name": "十月月报-复盘", "task_type": "复盘", "event": "EVT-202610-MONTHLY-ANCHOR", "status": "pending"},
        {"id": "TSK-2026-10-SCORE-01", "name": "G5 收入评分填写", "task_type": "评分", "deadline": "DL-G5-202610", "status": "pending"},
    ]
    for t in tasks:
        validate(ProjectTask, t, f"task-{t['id']}")

    deadlines = [
        {"id": "DL-M06-202610", "name": "2026-10 月报报送截止", "due_date": "2026-10-20", "deadline_type": "报送",
         "bound_milestone": "M06", "priority": "高", "status": "未到期", "alarm_rule": "提前3天告警+日报巡检"},
        {"id": "DL-G5-202610", "name": "2026-10 收入评分截止", "due_date": "2026-10-31", "deadline_type": "评分",
         "priority": "中", "status": "未到期", "alarm_rule": "提前5天告警"},
        {"id": "DL-M07-20260929", "name": "大兴开标", "due_date": "2026-09-29", "deadline_type": "开标",
         "bound_milestone": "M07", "priority": "高", "status": "已闭环", "alarm_rule": "开标后触发承接口径确认任务"},
    ]
    for d in deadlines:
        validate(Deadline, d, f"deadline-{d['id']}")

    orgs = [
        {"id": "org-jxj", "name": "房山区经济和信息化局", "org_type": "审批主体", "level": "区级"},
        {"id": "org-czj", "name": "房山区财政局", "org_type": "审批主体", "level": "区级"},
        {"id": "org-fsqwsj", "name": "房山区卫生健康委员会", "org_type": "行政监管", "level": "区级"},
        {"id": "org-bjwsj", "name": "北京市卫生健康委员会", "org_type": "行政监管", "level": "市级"},
        {"id": "org-dongruan", "name": "东软集团", "org_type": "供应商", "level": "委内", "contact": "（合同台账）"},
    ]
    for o in orgs:
        validate(OrgPilot, o, f"org-{o['id']}")

    # ── 5. 负对照（必须被拒绝；任一通过 = 校验器失效 = P1 失败） ──
    neg_controls = [
        ("Milestone", "⛔ 无阻塞原因", {"id": "NEG-BLOCKED", "date": "01-01", "title": "负对照-阻塞无原因",
                                        "severity": "⛔", "owner": "测试"}),
        ("ProjectTask", "done 无交付物", {"id": "NEG-TASK", "name": "负对照-门禁失守", "task_type": "报送",
                                            "status": "done"}),
        ("Milestone", "非法 severity", {"id": "NEG-SEV", "date": "01-01", "title": "负对照-非法状态",
                                         "severity": "??", "owner": "测试"}),
        ("Deadline", "负剩余天数", {"id": "NEG-DL", "name": "负对照-负数倒计时", "due_date": "2026-10-20",
                                     "deadline_type": "报送", "days_left": -3}),
    ]
    neg_models = {"Milestone": Milestone, "ProjectTask": ProjectTask, "Deadline": Deadline}
    for model, label, payload in neg_controls:
        rejected = False
        try:
            obj = neg_models[model](**payload)
        except Exception:
            rejected = True  # 结构/条件约束拒绝
        if not rejected:
            for rule_name, check in PILOT_RULES.get(model, []):
                if not check(obj):
                    rejected = True
                    break
        results["negative_controls"].append({"model": model, "label": label, "rejected": rejected})

    # ── 6. 汇总 ──
    ok = [i for i in results["instances"] if i["ok"]]
    bad = [i for i in results["instances"] if not i["ok"]]
    negs = results["negative_controls"]
    neg_ok = all(n["rejected"] for n in negs)
    results["summary"] = {
        "validated_instances": len(results["instances"]),
        "passed": len(ok),
        "failed": len(bad),
        "negative_controls": len(negs),
        "negative_controls_rejected": sum(1 for n in negs if n["rejected"]),
        "negative_controls_passed": neg_ok,
        "verdict": "PASS" if not bad and neg_ok else "FAIL",
    }
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results["summary"], ensure_ascii=False, indent=2))
    if bad:
        print("\nFAILED_INSTANCES:")
        for i in bad:
            print(" -", i["model"], i["name"], "|", i["detail"][:120])
    return 0 if results["summary"]["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
