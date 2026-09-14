from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from runtime.documents_plane.learning_decay import inspect_learning_decay
from runtime.documents_plane.paths import DocumentsPlanePathError


def _set_mtime(path: Path, value: date) -> None:
    timestamp = datetime(value.year, value.month, value.day, 12, 0, 0).timestamp()
    os.utime(path, (timestamp, timestamp))


def _concept_root(tmp_path: Path) -> tuple[Path, Path]:
    documents = tmp_path / "Documents"
    concepts = documents / "@学习进化" / "_knowledge" / "50-concepts"
    concepts.mkdir(parents=True)
    return documents, concepts


def test_scan_matches_legacy_age_buckets_and_reference_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    documents, concepts = _concept_root(tmp_path)
    files = {
        "fresh.md": date(2026, 8, 29),
        "aging.md": date(2026, 8, 5),
        "stale.md": date(2026, 7, 15),
        "decayed.md": date(2026, 6, 20),
    }
    for name, modified in files.items():
        path = concepts / name
        path.write_text(f"# {name}\n", encoding="utf-8")
        _set_mtime(path, modified)
    (concepts / "fresh.md").write_text("see aging.md and stale.md\n", encoding="utf-8")
    (concepts / "README.md").write_text("excluded\n", encoding="utf-8")
    (concepts / "_index.md").write_text("excluded\n", encoding="utf-8")

    monkeypatch.setattr("runtime.documents_plane.learning_decay._git_last_modified", lambda *_args: None)
    result = inspect_learning_decay(
        documents,
        domain_relative="@学习进化/_knowledge/50-concepts",
        mode="scan",
        today=date(2026, 8, 30),
    )

    assert result == {
        "schema": "runtime.documents-learning-decay.v1",
        "status": "attention",
        "mode": "scan",
        "checked_on": "2026-08-30",
        "concept_file_count": 4,
        "referenced_concept_count": 2,
        "orphan_concept_count": 2,
        "decay_candidate_count": 2,
        "staleness_counts": {
            "fresh": 1,
            "normal": 0,
            "aging": 1,
            "stale": 1,
            "decayed": 1,
            "uncommitted": 0,
        },
        "error": None,
    }


def test_orphan_mode_returns_aggregate_only_and_no_source_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    documents, concepts = _concept_root(tmp_path)
    (concepts / "root.md").write_text("# root\n", encoding="utf-8")
    (concepts / "linked.md").write_text("root.md\n", encoding="utf-8")
    monkeypatch.setattr("runtime.documents_plane.learning_decay._git_last_modified", lambda *_args: None)

    result = inspect_learning_decay(
        documents,
        domain_relative="@学习进化/_knowledge/50-concepts",
        mode="ls-orphan",
        today=date(2026, 8, 30),
    )

    assert result["mode"] == "ls-orphan"
    assert result["status"] == "attention"
    assert result["orphan_concept_count"] == 1
    assert result["referenced_concept_count"] == 1
    assert "root.md" not in json.dumps(result, ensure_ascii=False)
    assert "linked.md" not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize(
    "relative",
    ["../outside", "/absolute", "@学习进化/_knowledge/50-concepts/../outside"],
)
def test_learning_decay_rejects_unsafe_or_missing_roots(tmp_path: Path, relative: str) -> None:
    documents, _ = _concept_root(tmp_path)

    with pytest.raises(DocumentsPlanePathError):
        inspect_learning_decay(documents, domain_relative=relative, mode="scan", today=date(2026, 8, 30))


def _binding(tmp_path: Path) -> dict[str, str]:
    documents, concepts = _concept_root(tmp_path)
    (concepts / "one.md").write_text("# one\n", encoding="utf-8")
    l4_registry = documents / "@公共" / "_control" / "L4-DOMAIN-REGISTRY.yaml"
    l4_registry.parent.mkdir(parents=True)
    l4_registry.write_text("kind: registry\n", encoding="utf-8")
    binding = tmp_path / "documents-domain-projects.yaml"
    binding.write_text(
        """runtime_jobs:
  - id: documents-weijian-controller-shadow
    domain_id: work-weijian
    owner: runtime-control
    action: shadow_legacy_controller
    schedule: manual
    timeout_seconds: 30
    reads:
      - "@工作文档/卫健委/_control"
      - "@工作文档/卫健委/_entities"
      - "@工作文档/卫健委/_meta"
      - "@工作文档/卫健委/_runtime"
      - "@工作文档/卫健委/_storage"
      - "@工作文档/卫健委/_knowledge"
    writes: []
    evidence_relative_path: control/evidence/documents-weijian-controller-shadow/documents-weijian-controller-shadow.json
    evidence_schema: runtime.documents-controller-shadow.evidence.v2
    fail_closed: true
  - id: documents-learning-decay
    domain_id: vault
    owner: runtime-learning
    action: audit_concept_decay
    schedule: manual
    timeout_seconds: 60
    reads:
      - "@学习进化/_knowledge/50-concepts"
    writes: []
    evidence_relative_path: control/evidence/documents-learning-decay/documents-learning-decay.json
    evidence_schema: runtime.documents-learning-decay.evidence.v1
    fail_closed: true
  - id: documents-learning-orphans
    domain_id: vault
    owner: runtime-learning
    action: list_orphan_concepts
    schedule: manual
    timeout_seconds: 60
    reads:
      - "@学习进化/_knowledge/50-concepts"
    writes: []
    evidence_relative_path: control/evidence/documents-learning-orphans/documents-learning-orphans.json
    evidence_schema: runtime.documents-learning-decay.evidence.v1
    fail_closed: true
""",
        encoding="utf-8",
    )
    return {
        "DOCUMENTS_CONTENT_ROOT": str(documents),
        "OMOSTATION_RUNTIME_STATE_ROOT": str(tmp_path / "state"),
        "DOCUMENTS_DOMAIN_PROJECTS_REGISTRY": str(binding),
        "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
    }


def test_runtime_cli_registers_learning_owner_and_publishes_runtime_only_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from runtime.documents_plane.cli import main

    monkeypatch.setattr("runtime.documents_plane.commands._sandbox_argv", lambda command, _roots: command)
    environ = _binding(tmp_path)
    monkeypatch.setenv("PYTHONPATH", environ["PYTHONPATH"])

    exit_code = main(["documents", "run", "documents-learning-decay", "--json"], environ=environ)

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["job_id"] == "documents-learning-decay"
    assert payload["owner"] == "runtime-learning"
    assert payload["evidence_error"] is None
    assert payload["evidence_path"].startswith(environ["OMOSTATION_RUNTIME_STATE_ROOT"])
    assert not payload["evidence_path"].startswith(environ["DOCUMENTS_CONTENT_ROOT"])
    receipt = json.loads(Path(payload["evidence_path"]).read_text(encoding="utf-8"))
    assert receipt["owner_evidence"]["schema"] == "runtime.documents-learning-decay.v1"
    assert receipt["owner_evidence"]["concept_file_count"] == 1
    assert "one.md" not in json.dumps(receipt, ensure_ascii=False)


def test_runtime_rejects_malformed_learning_owner_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime.documents_plane.cli import _learning_decay_job_spec
    from runtime.documents_plane.jobs import JobRegistry, run_job

    monkeypatch.setattr("runtime.documents_plane.commands._sandbox_argv", lambda command, _roots: command)
    environ = _binding(tmp_path)
    spec = _learning_decay_job_spec(environ, job_id="documents-learning-decay", action="audit_concept_decay")
    registry = JobRegistry()
    registry.register(spec, [sys.executable, "-c", "print('{}')"])

    result = run_job(
        registry,
        "documents-learning-decay",
        documents_root=Path(environ["DOCUMENTS_CONTENT_ROOT"]),
        state_root=Path(environ["OMOSTATION_RUNTIME_STATE_ROOT"]),
    )

    assert result.exit_code == 74
    assert result.evidence_error == "learning-decay evidence has an invalid schema"


def test_runtime_cli_dry_run_does_not_start_owner_or_create_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from runtime.documents_plane.cli import main

    monkeypatch.setattr("runtime.documents_plane.commands._sandbox_argv", lambda command, _roots: command)
    environ = _binding(tmp_path)

    exit_code = main(["documents", "run", "documents-learning-orphans", "--dry-run", "--json"], environ=environ)

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["dry_run"] is True
    assert payload["job_id"] == "documents-learning-orphans"
    assert not Path(environ["OMOSTATION_RUNTIME_STATE_ROOT"]).exists()


def test_installed_runtime_cli_routes_documents_without_a_second_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from runtime.cli import main as runtime_main

    monkeypatch.setattr("runtime.documents_plane.commands._sandbox_argv", lambda command, _roots: command)
    environ = _binding(tmp_path)
    for key, value in environ.items():
        monkeypatch.setenv(key, value)

    exit_code = runtime_main(["documents", "run", "documents-learning-orphans", "--dry-run", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["job_id"] == "documents-learning-orphans"
    assert payload["dry_run"] is True
