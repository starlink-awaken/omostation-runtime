from __future__ import annotations

from pathlib import Path

import yaml


def _valid_fact(fid: str) -> dict[str, object]:
    return {
        "fid": fid,
        "type": "info",
        "trust": "confirmed",
        "importance": "medium",
        "statement": "卫健委事实样本",
        "summary": "事实样本",
        "verified_at": "2026-08-13",
        "expiry": "2026-11-11",
        "entity_ids": ["entity-demo"],
        "status": "active",
    }


def _make_domain(tmp_path: Path, facts: list[dict[str, object]]) -> Path:
    domain = tmp_path / "@工作文档" / "卫健委"
    facts_dir = domain / "_entities" / "facts"
    facts_dir.mkdir(parents=True)
    (facts_dir / "00-info.yaml").write_text(
        yaml.safe_dump({"facts": facts}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (facts_dir / "_index.yaml").write_text(
        yaml.safe_dump(
            {"facts_total": len(facts), "by_type": {"info": len(facts)}},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return domain


def test_audit_facts_counts_valid_yaml_without_writing_domain(tmp_path: Path) -> None:
    from runtime.documents_plane.facts import audit_facts

    domain = _make_domain(tmp_path, [_valid_fact("fact-20260813-001")])

    result = audit_facts(domain)

    assert result.status == "ok"
    assert result.facts_total == 1
    assert result.by_type == {"info": 1}
    assert result.errors == ()
    assert result.warnings == ()
    assert (domain / "_entities" / "facts" / "00-info.yaml").exists()


def test_audit_facts_rejects_symlinked_fact_file(tmp_path: Path) -> None:
    from runtime.documents_plane.facts import audit_facts

    domain = _make_domain(tmp_path, [])
    outside = tmp_path / "outside.yaml"
    outside.write_text(
        yaml.safe_dump(
            {"facts": [_valid_fact("fact-20260813-001")]},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    fact_link = domain / "_entities" / "facts" / "00-info.yaml"
    fact_link.unlink()
    fact_link.symlink_to(outside)

    result = audit_facts(domain)

    assert result.status == "invalid"
    assert any("not a regular fact file" in error for error in result.errors)
