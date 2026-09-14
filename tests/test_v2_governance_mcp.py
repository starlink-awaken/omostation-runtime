"""Integration tests for V2 Governance FastMCP tool handlers in Runtime."""

from __future__ import annotations

from runtime.mcp_server import (
    handle_cartridge_inspect,
    handle_cartridge_list,
    handle_intent_compile,
    handle_shadow_challenge,
)


def test_runtime_intent_compile_tool() -> None:
    res = handle_intent_compile("关于全省全民健康信息平台跨区域互认立项规划方案", domain="auto")
    assert "detected_domain" in res
    assert res["detected_domain"] == "work-weijian"
    assert len(res["policy_requirements"]) >= 2
    assert len(res["agent_dag"]) == 4


def test_runtime_shadow_challenge_tool() -> None:
    text = "项目总预算 2000 万元，直接连接公网医疗数据库。"
    res = handle_shadow_challenge(text, domain="work-weijian", auto_patch=True)
    assert res["passed"] is False
    assert len(res["challenges"]) >= 1
    assert res["patched_text"] is not None


def test_runtime_cartridge_tools() -> None:
    lst = handle_cartridge_list()
    assert lst["cartridges_count"] >= 2

    inspect = handle_cartridge_inspect("cartridge-weijian-v1")
    assert inspect["cartridge_id"] == "cartridge-weijian-v1"
    assert "manifest" in inspect["data"]
