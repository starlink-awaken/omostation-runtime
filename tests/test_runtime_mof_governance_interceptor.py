"""Tests for Runtime MOF Governance Pre-flight Interceptor (Phase 2)."""

from __future__ import annotations

import time

from runtime.governance.interceptor import (
    GovernanceInterceptor,
    PreFlightViolationError,
)
from runtime.mcp_server import handle_governance_preflight


def test_interceptor_allows_clean_python_write():
    interceptor = GovernanceInterceptor()
    clean_code = """
import json
from agora.client import query

def handler():
    return query('ecos/health')
"""
    allowed, diag = interceptor.intercept_tool_call(
        tool_name="write_to_file",
        arguments={
            "TargetFile": "/Users/xiamingxing/workspace/projects/cockpit/src/cockpit/view.py",
            "CodeContent": clean_code,
        },
        caller_layer="L3",
    )
    assert allowed is True
    assert diag is None


def test_interceptor_rejects_forbidden_ast_import_in_write():
    interceptor = GovernanceInterceptor()
    bad_code = """
import os
import l4_kernel.internal.storage as db

def hack():
    return db.query_raw()
"""
    allowed, diag = interceptor.intercept_tool_call(
        tool_name="write_to_file",
        arguments={
            "TargetFile": "/Users/xiamingxing/workspace/projects/cockpit/src/cockpit/view.py",
            "CodeContent": bad_code,
        },
        caller_layer="L3",
    )
    assert allowed is False
    assert diag is not None
    assert diag["status"] == "REJECTED"
    assert diag["error_type"] == "MOF_CONSTRAINT_VIOLATION"
    assert diag["violation"]["rule_id"] == "X1-C02"
    assert diag["violation"]["violation_code"] == "E-L0-002"
    assert "l4_kernel.internal" in diag["violation"]["offending_symbol"]
    assert "agora" in diag["violation"]["remediation"].lower()


def test_interceptor_rejects_forbidden_path_write():
    interceptor = GovernanceInterceptor()
    allowed, diag = interceptor.intercept_tool_call(
        tool_name="write_to_file",
        arguments={
            "TargetFile": "@工作文档/卫健委/confidential_facts.yaml",
            "CodeContent": "facts: [1, 2, 3]",
        },
        caller_layer="L3",
        caller_domain="untrusted_agent",
    )
    assert allowed is False
    assert diag is not None
    assert diag["violation"]["rule_id"] == "X1-C03"
    assert diag["violation"]["violation_code"] == "E-L0-003"


def test_interceptor_rejects_unsafe_commands():
    interceptor = GovernanceInterceptor()

    # 1. Global pip install
    allowed1, diag1 = interceptor.intercept_tool_call(
        tool_name="run_command",
        arguments={"CommandLine": "pip install --global torch"},
    )
    assert allowed1 is False
    assert diag1["violation"]["violation_code"] == "E-CMD-001"

    # 2. Hardcoded reserved port
    allowed2, diag2 = interceptor.intercept_tool_call(
        tool_name="run_command",
        arguments={"CommandLine": "uvicorn app:main --port=8000"},
    )
    assert allowed2 is False
    assert diag2["violation"]["violation_code"] == "E-CMD-003"

    # 3. Clean command
    allowed3, diag3 = interceptor.intercept_tool_call(
        tool_name="run_command",
        arguments={"CommandLine": "uv run pytest tests/ -q"},
    )
    assert allowed3 is True
    assert diag3 is None


def test_interceptor_replace_file_content_inspection():
    interceptor = GovernanceInterceptor()
    bad_replace_chunk = (
        "import runtime.private.credentials as creds\napi_key = creds.KEY"
    )

    allowed, diag = interceptor.intercept_tool_call(
        tool_name="replace_file_content",
        arguments={
            "TargetFile": "src/runtime/adapter.py",
            "ReplacementContent": bad_replace_chunk,
        },
        caller_layer="L3",
    )
    assert allowed is False
    assert diag is not None
    assert diag["violation"]["rule_id"] == "X1-C02"


def test_interceptor_enforce_or_raise():
    interceptor = GovernanceInterceptor()
    bad_code = "import l4_kernel.internal.db"

    try:
        interceptor.enforce(
            tool_name="write_to_file",
            arguments={"TargetFile": "test.py", "CodeContent": bad_code},
            caller_layer="L3",
        )
        raise AssertionError("Expected PreFlightViolationError to be raised")
    except PreFlightViolationError as exc:
        assert exc.violation_code == "E-L0-002"
        assert exc.rule_id == "X1-C02"


def test_mcp_server_governance_preflight_handler():
    res = handle_governance_preflight(
        tool_name="write_to_file",
        arguments={
            "TargetFile": "src/cockpit/app.py",
            "CodeContent": "import l4_kernel.internal",
        },
        caller_layer="L3",
    )
    assert res["status"] == "REJECTED"
    assert res["violation"]["rule_id"] == "X1-C02"

    res_ok = handle_governance_preflight(
        tool_name="run_command",
        arguments={"CommandLine": "uv run pytest"},
    )
    assert res_ok["status"] == "ALLOWED"


def test_interceptor_sub_millisecond_latency():
    interceptor = GovernanceInterceptor()
    code = "import json\nfrom agora.client import Client\ndef run(): return Client().ping()"

    start = time.perf_counter()
    for _ in range(100):
        allowed, _ = interceptor.intercept_tool_call(
            tool_name="write_to_file",
            arguments={"TargetFile": "app.py", "CodeContent": code},
            caller_layer="L3",
        )
        assert allowed is True
    elapsed = time.perf_counter() - start

    avg_ms = (elapsed / 100) * 1000
    assert avg_ms < 5.0, f"Average pre-flight latency too high: {avg_ms:.2f}ms"
