"""Tests for Runtime MOF Documents Dual-Plane Governance (ADR-0191)."""

from __future__ import annotations

from pathlib import Path

import pytest
from runtime.governance.interceptor import GovernanceInterceptor
from runtime.mcp_server import (
    handle_documents_audit,
    handle_documents_guardrails,
    handle_governance_preflight,
)


def test_interceptor_catches_documents_script_write():
    interceptor = GovernanceInterceptor()
    allowed, diag = interceptor.intercept_tool_call(
        tool_name="write_to_file",
        arguments={
            "TargetFile": "/Users/xiamingxing/Documents/@工作文档/卫健委/bad_tool.py",
            "CodeContent": "import os\nprint('bad')",
        },
        caller_layer="L3",
        caller_domain="work-weijian",
    )

    assert not allowed
    assert diag is not None
    assert diag["status"] == "REJECTED"
    v = diag["violation"]
    assert v["violation_code"] == "E-DOC-001"
    assert "禁止在 Documents 内容域写入可执行代码脚本" in v["summary"]
    assert "suggested_patch" in v


def test_interceptor_allows_documents_markdown_write():
    interceptor = GovernanceInterceptor()
    allowed, diag = interceptor.intercept_tool_call(
        tool_name="write_to_file",
        arguments={
            "TargetFile": "/Users/xiamingxing/Documents/@工作文档/卫健委/2026-08-17-周报.md",
            "CodeContent": "# 卫健委信息化周报",
        },
        caller_layer="L3",
        caller_domain="work-weijian",
    )

    assert allowed
    assert diag is None


def test_handle_documents_guardrails():
    res = handle_documents_guardrails("work-weijian")
    assert res["domain"] == "work-weijian"
    prompt = res["documents_guardrail_prompt"]
    assert "<documents_dual_plane_guardrails" in prompt
    assert "E-DOC-001" in prompt


def test_handle_documents_audit(tmp_path: Path):
    doc_dir = tmp_path / "Documents" / "@家庭生活"
    doc_dir.mkdir(parents=True)
    script_file = doc_dir / "automation.sh"
    script_file.write_text("#!/bin/bash\necho 1", encoding="utf-8")

    res = handle_documents_audit(path=str(doc_dir), domain="family")
    assert res["status"] == "VIOLATIONS_FOUND"
    assert res["violations_count"] >= 1
    assert any(v["violation_code"] == "E-DOC-001" for v in res["violations"])


def test_handle_governance_preflight_for_documents():
    res = handle_governance_preflight(
        tool_name="write_to_file",
        arguments={
            "TargetFile": "~/Documents/@学习进化/run.py",
            "CodeContent": "print(1)",
        },
        caller_layer="L3",
        caller_domain="learning",
    )
    assert res["status"] == "REJECTED"
    assert res["violation"]["violation_code"] == "E-DOC-001"
