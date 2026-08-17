"""Tests for FastMCP domain compliance and pitfall check tools in runtime (ADR-0193 / ADR-0194)."""

from __future__ import annotations

from runtime.mcp_server import handle_domain_compliance_audit, handle_pitfall_check


def test_handle_domain_compliance_audit_detection():
    # 1. Non-compliant health informatics text
    text_bad = "某医院电子病历平台二期投资预算 900 万元，采用公有云部署。"
    res_bad = handle_domain_compliance_audit(text_bad, domain="work-weijian")
    assert res_bad["passed"] is False
    assert any(v["rule_id"] == "E-POL-WJ-001" for v in res_bad["violations"])

    # 2. Compliant text
    text_good = "某医院电子病历平台二期投资预算 450 万元，经专家论证通过，全面落实等保三级与国密安全。"
    res_good = handle_domain_compliance_audit(text_good, domain="work-weijian")
    assert res_good["passed"] is True


def test_handle_pitfall_check_detection(tmp_path):
    bad_py = tmp_path / "bad.py"
    bad_py.write_text("p_out.write_text('bad')\n", encoding="utf-8")
    res = handle_pitfall_check(str(bad_py))
    assert res["passed"] is False
    assert res["total_matches"] >= 1
    assert res["matches"][0]["pitfall_id"] == "PITFALL-001"
