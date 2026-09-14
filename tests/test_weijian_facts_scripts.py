from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

_SCRIPTS = Path(__file__).parents[1] / "scripts" / "weijian_facts"


def _fact() -> dict[str, object]:
    return {
        "fid": "fact-20260813-001",
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


def _domain(tmp_path: Path) -> Path:
    domain = tmp_path / "卫健委"
    facts_dir = domain / "_entities" / "facts"
    facts_dir.mkdir(parents=True)
    (facts_dir / "00-info.yaml").write_text(
        yaml.safe_dump({"facts": [_fact()]}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (facts_dir / "_index.yaml").write_text(
        yaml.safe_dump(
            {"facts_total": 1, "by_type": {"info": 1}, "expired_active": 0},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (domain / "_entities" / "models").mkdir()
    (domain / "_entities" / "entities").mkdir()
    (domain / "_runtime" / "skills").mkdir(parents=True)
    (domain / "_storage" / "05-交付区").mkdir(parents=True)
    (domain / "_control").mkdir()
    return domain


def _run(script_name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPTS / script_name), *args],
        capture_output=True,
        check=False,
        text=True,
    )


def test_facts_view_script_uses_explicit_root(tmp_path: Path) -> None:
    domain = _domain(tmp_path)

    result = _run("gen-facts-view.py", "--root", str(domain))

    assert result.returncode == 0, result.stderr
    view = (domain / "_entities" / "facts.md").read_text(encoding="utf-8")
    assert "fact-20260813-001" in view
    assert "YAML 双轨" in view


def test_legacy_migration_script_uses_explicit_root(tmp_path: Path) -> None:
    domain = _domain(tmp_path)
    (domain / "_entities" / "facts.md").write_text(
        "## 活跃事实\n"
        "| 事实陈述 | 类型 | 数值 | 重要性 | 来源 | 可信度 | 验证日 | 过期日 | 关联实体 |\n"
        "| 示例 | 📄信息 | - | 🔵 | 测试 | confirmed | 2026-08-13 | 2026-11-11 | entity-demo |\n"
        "## 事实生命周期规则\n",
        encoding="utf-8",
    )

    result = _run("migrate-facts-yaml.py", "--root", str(domain))

    assert result.returncode == 0, result.stderr
    assert (domain / "_entities" / "facts" / "06-info.yaml").exists()


def test_dashboard_script_uses_explicit_root_and_out_path(tmp_path: Path) -> None:
    domain = _domain(tmp_path)
    output = tmp_path / "dashboard.md"

    result = _run("gen-dashboard.py", "--root", str(domain), "--out", str(output))

    assert result.returncode == 0, result.stderr
    assert "事实基座 | **1** 条" in output.read_text(encoding="utf-8")
