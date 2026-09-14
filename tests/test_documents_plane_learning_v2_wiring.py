"""Wiring tests for the V2 read-only learning owner jobs (binding SSOT → registry)."""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import pytest


def _set_mtime(path: Path, value: date) -> None:
    timestamp = datetime(value.year, value.month, value.day, 12, 0, 0).timestamp()
    os.utime(path, (timestamp, timestamp))


def _binding_v2(tmp_path: Path) -> dict[str, str]:
    """Build a binding registry declaring exactly one V2 job plus fixtures."""

    documents = tmp_path / "Documents"
    concepts = documents / "@学习进化" / "_knowledge" / "50-concepts"
    concepts.mkdir(parents=True)
    (concepts / "one.md").write_text(
        "---\nknowledge_type: fact\nstatus: current\nsource: 官方文档\n---\n相关: [[x]]\nsource: 官方文档\n",
        encoding="utf-8",
    )
    _set_mtime(concepts / "one.md", date(2026, 8, 30))
    binding = tmp_path / "documents-domain-projects.yaml"
    binding.write_text(
        "\n".join(
            [
                "runtime_jobs:",
                "  - id: documents-weijian-controller-shadow",
                "    domain_id: work-weijian",
                "    owner: runtime-control",
                "    action: shadow_legacy_controller",
                "    schedule: manual",
                "    timeout_seconds: 30",
                "    reads:",
                '      - "@工作文档/卫健委/_control"',
                '      - "@工作文档/卫健委/_entities"',
                '      - "@工作文档/卫健委/_meta"',
                '      - "@工作文档/卫健委/_runtime"',
                '      - "@工作文档/卫健委/_storage"',
                '      - "@工作文档/卫健委/_knowledge"',
                "    writes: []",
                "    evidence_relative_path: control/evidence/documents-weijian-controller-shadow/documents-weijian-controller-shadow.json",
                "    evidence_schema: runtime.documents-controller-shadow.evidence.v2",
                "    fail_closed: true",
                "  - id: documents-learning-validate",
                "    domain_id: vault",
                "    owner: runtime-learning",
                "    action: validate_concept_cards",
                "    schedule: manual",
                "    timeout_seconds: 60",
                "    reads:",
                '      - "@学习进化/_knowledge/50-concepts"',
                "    writes: []",
                "    evidence_relative_path: control/evidence/documents-learning-validate/documents-learning-validate.json",
                "    evidence_schema: runtime.documents-learning-validate.evidence.v1",
                "    fail_closed: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "DOCUMENTS_CONTENT_ROOT": str(documents),
        "DOCUMENTS_DOMAIN_PROJECTS_REGISTRY": str(binding),
        "OMOSTATION_RUNTIME_STATE_ROOT": str(tmp_path / "runtime-state"),
        "PYTHONPATH": "src",
    }


def test_v2_owner_registers_and_publishes_runtime_only_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("yaml")
    from runtime.documents_plane.cli import main

    monkeypatch.setattr("runtime.documents_plane.commands._sandbox_argv", lambda command, _roots: command)
    environ = _binding_v2(tmp_path)
    monkeypatch.setenv("PYTHONPATH", environ["PYTHONPATH"])

    exit_code = main(["documents", "run", "documents-learning-validate", "--json"], environ=environ)

    payload = json.loads(capsys.readouterr().out)
    assert payload["job_id"] == "documents-learning-validate"
    assert payload["owner"] == "runtime-learning"
    assert payload["evidence_error"] is None
    assert payload["evidence_path"].startswith(environ["OMOSTATION_RUNTIME_STATE_ROOT"])
    assert not payload["evidence_path"].startswith(environ["DOCUMENTS_CONTENT_ROOT"])
    receipt = json.loads(Path(payload["evidence_path"]).read_text(encoding="utf-8"))
    assert "one.md" not in json.dumps(receipt, ensure_ascii=False)  # aggregate-only 泄露面控制


def test_v2_job_rejects_missing_binding_declaration(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    from runtime.documents_plane.cli import _learning_v2_job_spec
    from runtime.documents_plane.paths import DocumentsPlanePathError

    binding = tmp_path / "documents-domain-projects.yaml"
    binding.write_text("runtime_jobs: []\n", encoding="utf-8")
    environ = {"DOCUMENTS_DOMAIN_PROJECTS_REGISTRY": str(binding)}
    try:
        _learning_v2_job_spec(environ, job_id="documents-learning-validate", action="validate_concept_cards")
    except DocumentsPlanePathError as exc:
        assert "exactly once" in str(exc)
    else:
        raise AssertionError("missing declaration must be rejected")


def test_v2_job_rejects_invalid_contract(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    from runtime.documents_plane.cli import _learning_v2_job_spec
    from runtime.documents_plane.paths import DocumentsPlanePathError

    binding = tmp_path / "documents-domain-projects.yaml"
    binding.write_text(
        "runtime_jobs:\n"
        "  - id: documents-learning-validate\n"
        "    domain_id: vault\n"
        "    owner: wrong-owner\n"
        "    action: validate_concept_cards\n"
        "    schedule: manual\n"
        "    timeout_seconds: 60\n"
        "    writes: []\n"
        "    fail_closed: true\n",
        encoding="utf-8",
    )
    environ = {"DOCUMENTS_DOMAIN_PROJECTS_REGISTRY": str(binding)}
    try:
        _learning_v2_job_spec(environ, job_id="documents-learning-validate", action="validate_concept_cards")
    except DocumentsPlanePathError as exc:
        assert "invalid contract" in str(exc)
    else:
        raise AssertionError("invalid contract must be rejected")
