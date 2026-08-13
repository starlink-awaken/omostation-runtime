from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pytest


def _domain(documents_root: Path) -> Path:
    domain = documents_root / "@工作文档" / "卫健委"
    for relative_path, reviewed_on in (
        ("_control/signals.md", "2026-08-13"),
        ("_entities/facts.md", "2026-07-01"),
        ("_meta/model.md", "2026-05-01"),
        ("_runtime/README.md", "2026-08-01"),
        ("_storage/notes.md", "2026-08-13"),
        ("_knowledge/guide.md", "2026-08-13"),
    ):
        path = domain / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\nlast-reviewed: {reviewed_on}\n---\n# Fixture\n",
            encoding="utf-8",
        )
    (domain / "_control" / "signals.md").write_text(
        "- type: 🔴\n- type: ⚠️\n- type: ⚠️\n- type: ⚠️\n",
        encoding="utf-8",
    )
    return domain


def test_controller_shadow_reports_covered_and_unmigrated_legacy_rules(
    tmp_path: Path,
) -> None:
    from runtime.documents_plane.controller_shadow import inspect_controller_shadow

    domain = _domain(tmp_path / "Documents")

    result = inspect_controller_shadow(domain, today=date(2026, 8, 13))

    assert result.as_dict() == {
        "covered_rule_ids": ["CR01", "CR02", "CR03", "CR05"],
        "freshness": {
            "invalid_reviewed_count": 0,
            "scanned_markdown_count": 5,
            "stale_30_60_count": 1,
            "stale_60_count": 1,
            "unreadable_regular_file_count": 0,
        },
        "legacy_controller_replaced": False,
        "schema": "runtime.documents-controller-shadow.v1",
        "signal_counts": {"ok": 0, "red": 1, "warning": 3},
        "status": "shadow_incomplete",
        "unmigrated_rule_ids": ["CR08", "CR23", "CR24", "CR25", "CR26", "CR29", "CR30"],
    }


def test_controller_shadow_rejects_a_symlinked_plane(tmp_path: Path) -> None:
    from runtime.documents_plane.controller_shadow import inspect_controller_shadow

    domain = _domain(tmp_path / "Documents")
    external = tmp_path / "external-control"
    external.mkdir()
    (external / "signals.md").write_text("- type: 🔴\n", encoding="utf-8")
    (domain / "_control" / "signals.md").unlink()
    (domain / "_control").rmdir()
    os.symlink(external, domain / "_control")

    with pytest.raises(ValueError, match="plane must be a direct directory"):
        inspect_controller_shadow(domain, today=date(2026, 8, 13))


def test_controller_shadow_job_refuses_binding_contract_drift(tmp_path: Path) -> None:
    from runtime.documents_plane.cli import _controller_shadow_job_spec
    from runtime.documents_plane.paths import DocumentsPlanePathError

    registry = tmp_path / "documents-domain-projects.yaml"
    registry.write_text(
        """runtime_jobs:
  - id: documents-weijian-controller-shadow
    domain_id: work-weijian
    owner: runtime-control
    action: shadow_legacy_controller
    schedule: manual
    timeout_seconds: 30
    reads: [\"@工作文档/卫健委/_control\"]
    writes: []
    evidence_relative_path: control/evidence/renamed/receipt.json
    evidence_schema: runtime.documents-controller-shadow.evidence.v1
    fail_closed: true
""",
        encoding="utf-8",
    )

    with pytest.raises(DocumentsPlanePathError, match="invalid contract"):
        _controller_shadow_job_spec(
            {"DOCUMENTS_DOMAIN_PROJECTS_REGISTRY": str(registry)}
        )


def test_controller_shadow_job_records_incomplete_parity_outside_documents(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from runtime.documents_plane.cli import main

    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    documents_root = tmp_path / "Documents"
    domain = _domain(documents_root)
    source_root = Path(__file__).parents[1] / "src"
    registry_path = (
        tmp_path
        / "workspace"
        / ".omo"
        / "_truth"
        / "registry"
        / "documents-domain-projects.yaml"
    )
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        """runtime_jobs:
  - id: documents-weijian-controller-shadow
    domain_id: work-weijian
    owner: runtime-control
    action: shadow_legacy_controller
    schedule: manual
    timeout_seconds: 30
    reads:
      - \"@工作文档/卫健委/_control\"
      - \"@工作文档/卫健委/_entities\"
      - \"@工作文档/卫健委/_meta\"
      - \"@工作文档/卫健委/_runtime\"
      - \"@工作文档/卫健委/_storage\"
      - \"@工作文档/卫健委/_knowledge\"
    writes: []
    evidence_relative_path: control/evidence/documents-weijian-controller-shadow/documents-weijian-controller-shadow.json
    evidence_schema: runtime.documents-controller-shadow.evidence.v1
    fail_closed: true
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(source_root))

    exit_code = main(
        ["documents", "run", "documents-weijian-controller-shadow", "--json"],
        environ={
            "DOCUMENTS_CONTENT_ROOT": str(documents_root),
            "OMOSTATION_RUNTIME_STATE_ROOT": str(tmp_path / "state"),
            "DOCUMENTS_DOMAIN_PROJECTS_REGISTRY": str(registry_path),
            "PYTHONPATH": str(source_root),
        },
    )

    result = json.loads(capsys.readouterr().out)
    receipt = json.loads(Path(result["evidence_path"]).read_text(encoding="utf-8"))
    assert exit_code == 1
    assert result["job_id"] == "documents-weijian-controller-shadow"
    assert result["owner"] == "runtime-control"
    assert result["evidence_error"] is None
    assert result["evidence_path"] == str(
        tmp_path
        / "state"
        / "control"
        / "evidence"
        / "documents-weijian-controller-shadow"
        / "documents-weijian-controller-shadow.json"
    )
    assert json.loads(result["stdout"])["status"] == "shadow_incomplete"
    assert receipt["owner_evidence"] == {
        "covered_rule_ids": ["CR01", "CR02", "CR03", "CR05"],
        "covered_rule_count": 4,
        "legacy_controller_replaced": False,
        "schema": "runtime.documents-controller-shadow.evidence.v1",
        "status": "shadow_incomplete",
        "unmigrated_rule_ids": [
            "CR08",
            "CR23",
            "CR24",
            "CR25",
            "CR26",
            "CR29",
            "CR30",
        ],
        "unmigrated_rule_count": 7,
    }
    assert not (domain / "_runtime" / "巡检报告").exists()
    assert "signals.md" not in json.dumps(receipt, ensure_ascii=False)
