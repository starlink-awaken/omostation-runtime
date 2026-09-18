from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

TOOLS = Path(__file__).resolve().parents[1] / "scripts" / "kems-v2"


def run_tool(script: str, *args: str, expected: int = 0) -> str:
    result = subprocess.run(
        [sys.executable, TOOLS / script, *args],
        check=False,
        text=True,
        capture_output=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode == expected, output
    return output


def make_domain(root: Path) -> None:
    run_tool("kems-init.py", "--root", str(root))
    (root / "DOMAIN.yaml").write_text(
        "id: test-domain\ndisplay_name: Test Domain\n", encoding="utf-8"
    )
    control = root / "_control"
    control.mkdir(exist_ok=True)
    (control / "key-milestones.yaml").write_text(
        "version: 1.0\n"
        "milestones:\n"
        "  - id: ms-test\n"
        "    date: '12-31'\n"
        "    title: rebuild acceptance\n"
        "    severity: ✅\n"
        "    owner: runtime\n",
        encoding="utf-8",
    )

    ontology = root / "_entities" / "ontology"
    (ontology / "classes.yaml").write_text(
        "classes:\n"
        "  - {id: C1, code: entity, name_cn: 实体, instance_count: 1}\n"
        "  - {id: C3, code: project, name_cn: 项目, instance_count: 1}\n",
        encoding="utf-8",
    )
    (ontology / "relations.yaml").write_text(
        "relations:\n  - {id: R1, code: relates_to}\n", encoding="utf-8"
    )
    (ontology / "instances.yaml").write_text(
        "total_instances: 2\n"
        "instances:\n"
        "  - {id: entity-one, class: C1, name: Entity One}\n"
        "  - {id: proj-rebuild, class: C3, name: Rebuild, status: active, note: '12万'}\n",
        encoding="utf-8",
    )
    (ontology / "associations.yaml").write_text(
        "total_edges: 1\n"
        "edges:\n"
        "  - {id: edge-one, source: entity-one, relation: R1, target: proj-rebuild}\n",
        encoding="utf-8",
    )
    (root / "_entities" / "facts" / "00-budget.yaml").write_text(
        "facts:\n"
        "  - id: fact-one\n"
        "    type: budget\n"
        "    status: active\n"
        "    statement: rebuild budget is 12万\n"
        "    expiry: 2099-12-31\n",
        encoding="utf-8",
    )
    (root / "_entities" / "facts" / "_index.yaml").write_text(
        "facts_total: 1\n"
        "by_type:\n  budget: 1\n"
        "per_file:\n"
        "  00-budget.yaml: 1\n"
        "  01-progress.yaml: 0\n"
        "  02-config.yaml: 0\n"
        "  03-event.yaml: 0\n"
        "  04-structure.yaml: 0\n"
        "  05-rule.yaml: 0\n"
        "  06-info.yaml: 0\n"
        "  07-relation.yaml: 0\n"
        "  08-indicator.yaml: 0\n"
        "expired_active: 0\n",
        encoding="utf-8",
    )
    (root / "_entities" / "models" / "rebuild.md").write_text(
        "---\n"
        "title: Rebuild\n"
        "status: active\n"
        "type: model\n"
        "owner: runtime\n"
        "created: 2026-09-18\n"
        "---\n"
        "# Rebuild\n\nproj-rebuild relates_to entity-one through R1.\n",
        encoding="utf-8",
    )


def test_kems_v2_rebuild_is_workspace_native_and_cross_domain(tmp_path: Path) -> None:
    domains = [tmp_path / f"domain-{index}" for index in range(4)]
    for domain in domains:
        make_domain(domain)

    for domain in domains:
        root = str(domain)
        assert "documents" not in run_tool("check-ssot-sync.py", "--root", root).lower()
        run_tool("check-ontology-consistency.py", "--root", root)
        run_tool("check-model-conformance.py", "--root", root)
        run_tool("check-critical-path.py", "--root", root)

        ask = run_tool(
            "model-ask.py", "--root", root, "--query", "rebuild", "--top-k", "3"
        )
        assert "rebuild" in ask.lower()

        run_tool("graph-query.py", "--root", root, "--stats")
        run_tool("graph-query.py", "--root", root, "--neighbors", "entity-one")
        run_tool("kems-snapshot.py", "--root", root)

        report = run_tool("gen-report-view.py", "--root", root, "--stdout")
        assert "Rebuild" in report
        output = run_tool("kems-toolkit.py", "--root", root, "--mode", "check", "--dry-run")
        assert "KEMS 强制更新检查" in output

        run_tool("refresh-indexes.py", "--root", root)
        assert (domain / "_knowledge" / "索引目录" / "全局文件索引.md").is_file()

        snapshot_files = list((domain / "_storage" / "06-工具" / "运行产物").glob("*.json"))
        assert snapshot_files
        snapshot = json.loads(snapshot_files[-1].read_text(encoding="utf-8"))
        assert snapshot["facts"]["total"] == 1
        assert snapshot["ontology"] == {"instances": 2, "edges": 1}

    joined = ",".join(str(domain) for domain in domains)
    cross = run_tool("kems-cross-check.py", "--domains", joined)
    assert cross.count("PASS ") == 4
    assert "Documents" not in cross


def test_kems_v2_has_no_documents_default_paths() -> None:
    forbidden = ("/Users/xiamingxing", "~/Documents", "DEFAULT_DOMAINS")
    for script in TOOLS.glob("*.py"):
        text = script.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, (script.name, token)
