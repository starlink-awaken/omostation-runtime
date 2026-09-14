from __future__ import annotations

import json
import shlex
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

# isort: split
from runtime.documents_plane.jobs import JobRegistry, JobSpec, run_job


def _spec() -> JobSpec:
    return JobSpec(
        job_id="contract-check",
        reads=("contracts/documents-plane.yaml",),
        writes=("receipts/contract-check.json",),
        owner="l4",
        schedule="manual",
        timeout=1,
        evidence_path="evidence/contract-check.json",
        fail_closed=True,
    )


def _model_freshness_binding_environ(tmp_path: Path) -> dict[str, str]:
    documents_root = tmp_path / "Documents"
    registry_path = tmp_path / "documents-domain-projects.yaml"
    registry_path.write_text(
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
  - id: documents-weijian-model-freshness
    domain_id: work-weijian
    owner: runtime-control
    action: audit_model_freshness
    schedule: manual
    timeout_seconds: 30
    reads:
      - "@工作文档/卫健委/_entities/facts.md"
      - "@工作文档/卫健委/_entities/models"
    writes: []
    evidence_relative_path: control/evidence/documents-weijian-model-freshness/documents-weijian-model-freshness.json
    evidence_schema: runtime.documents-model-freshness.evidence.v1
    fail_closed: true
""",
        encoding="utf-8",
    )
    return {
        "DOCUMENTS_CONTENT_ROOT": str(documents_root),
        "OMOSTATION_RUNTIME_STATE_ROOT": str(tmp_path / "state"),
        "DOCUMENTS_DOMAIN_PROJECTS_REGISTRY": str(registry_path),
        "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
    }


def _write_model_freshness_fixture(documents_root: Path, *, facts_reviewed: str, model_reviewed: str) -> None:
    entities = documents_root / "@工作文档" / "卫健委" / "_entities"
    models = entities / "models"
    models.mkdir(parents=True)
    entities.joinpath("facts.md").write_text(f"last-reviewed: {facts_reviewed}\nfixture facts body\n", encoding="utf-8")
    models.joinpath("fixture-private-model.md").write_text(
        f"last-reviewed: {model_reviewed}\nfixture private model body\n",
        encoding="utf-8",
    )


def test_job_registry_rejects_duplicate_job_ids() -> None:
    registry = JobRegistry()
    registry.register(_spec(), [sys.executable, "-c", "pass"])

    with pytest.raises(ValueError, match="duplicate"):
        registry.register(_spec(), [sys.executable, "-c", "pass"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reads", ("../secret.md",)),
        ("writes", ("/tmp/escape.json",)),
        ("evidence_path", "../evidence.json"),
    ],
)
def test_job_registry_rejects_unsafe_declared_paths(field: str, value: object) -> None:
    registry = JobRegistry()
    unsafe_spec = replace(_spec(), **{field: value})

    with pytest.raises(ValueError, match="relative"):
        registry.register(unsafe_spec, [sys.executable, "-c", "pass"])


def test_dry_run_has_no_process_or_state_side_effects(tmp_path: Path) -> None:
    registry = JobRegistry()
    registry.register(_spec(), [sys.executable, "-c", "raise SystemExit(99)"])
    state_root = tmp_path / "state"
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()

    result = run_job(
        registry,
        "contract-check",
        dry_run=True,
        state_root=state_root,
        documents_root=documents_root,
    )

    assert result.dry_run is True
    assert result.exit_code == 0
    assert not state_root.exists()


def test_default_cli_registry_job_delegates_to_configured_l4_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The first shipped Documents job must be useful without caller injection."""
    from runtime.documents_plane.cli import main

    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    documents_root = tmp_path / "Documents"
    registry_path = documents_root / "@公共/_control/L4-DOMAIN-REGISTRY.yaml"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("kind: registry\n", encoding="utf-8")
    owner = tmp_path / "fake-l4-kernel"
    owner.write_text(
        "#!/bin/sh\n"
        'test "$1" = registry\n'
        'test "$2" = list\n'
        'test "$3" = --registry\n'
        f'test "$4" = {shlex.quote(str(registry_path))}\n'
        'test "$5" = --json\n'
        "printf '%s\\n' '{\"ok\":true}'\n",
        encoding="utf-8",
    )
    owner.chmod(0o755)
    exit_code = main(
        ["documents", "run", "l4-registry-list", "--json"],
        environ={
            "DOCUMENTS_CONTENT_ROOT": str(documents_root),
            "OMOSTATION_RUNTIME_STATE_ROOT": str(tmp_path / "state"),
            "L4_KERNEL_COMMAND": str(owner),
            "L4_DOMAIN_REGISTRY": str(registry_path),
        },
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["job_id"] == "l4-registry-list"
    assert payload["owner"] == "l4-kernel"
    assert payload["status"] == "succeeded"
    assert payload["stdout"] == '{"ok":true}\n'


def test_default_registry_declares_configured_registry_read_scope(
    tmp_path: Path,
) -> None:
    from runtime.documents_plane.cli import _default_registry

    documents_root = tmp_path / "Documents"
    registry_path = documents_root / "registries" / "custom.yaml"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("kind: registry\n", encoding="utf-8")

    spec, _ = _default_registry(
        {
            "DOCUMENTS_CONTENT_ROOT": str(documents_root),
            "L4_DOMAIN_REGISTRY": str(registry_path),
        }
    ).resolve("l4-registry-list")

    assert spec.reads == ("registries/custom.yaml",)


def test_default_registry_declares_read_only_weijian_facts_audit(
    tmp_path: Path,
) -> None:
    from runtime.documents_plane.cli import _default_registry

    spec, command = _default_registry({"DOCUMENTS_CONTENT_ROOT": str(tmp_path / "Documents")}).resolve(
        "documents-weijian-facts-audit"
    )

    assert spec.reads == ("@工作文档/卫健委/_entities/facts",)
    assert spec.writes == ()
    assert spec.owner == "runtime-facts"
    assert spec.schedule == "manual"
    assert command[-2:] == ("--domain-relative", "@工作文档/卫健委")


def test_default_cli_runs_weijian_facts_audit_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from runtime.documents_plane.cli import main

    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    documents_root = tmp_path / "Documents"
    facts_dir = documents_root / "@工作文档" / "卫健委" / "_entities" / "facts"
    facts_dir.mkdir(parents=True)
    facts_dir.joinpath("00-info.yaml").write_text(
        "facts:\n"
        "  - fid: fact-20260813-001\n"
        "    type: info\n"
        "    trust: confirmed\n"
        "    importance: medium\n"
        "    statement: 事实样本\n"
        "    summary: 样本\n"
        "    verified_at: '2026-08-13'\n"
        "    expiry: '2026-11-11'\n"
        "    entity_ids: [entity-demo]\n"
        "    status: active\n",
        encoding="utf-8",
    )
    facts_dir.joinpath("_index.yaml").write_text("facts_total: 1\nby_type: {info: 1}\n", encoding="utf-8")
    source_root = Path(__file__).parents[1] / "src"
    monkeypatch.setenv("PYTHONPATH", str(source_root))

    exit_code = main(
        ["documents", "run", "documents-weijian-facts-audit", "--json"],
        environ={
            "DOCUMENTS_CONTENT_ROOT": str(documents_root),
            "OMOSTATION_RUNTIME_STATE_ROOT": str(tmp_path / "state"),
            "PYTHONPATH": str(source_root),
        },
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["job_id"] == "documents-weijian-facts-audit"
    assert payload["status"] == "succeeded"
    assert json.loads(payload["stdout"])["facts_total"] == 1
    assert sorted(path.name for path in facts_dir.iterdir()) == [
        "00-info.yaml",
        "_index.yaml",
    ]


def test_weijian_facts_audit_persists_bounded_semantic_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cockpit must be able to project validation without reading Documents facts."""
    from runtime.documents_plane.cli import main

    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    documents_root = tmp_path / "Documents"
    facts_dir = documents_root / "@工作文档" / "卫健委" / "_entities" / "facts"
    facts_dir.mkdir(parents=True)
    facts_dir.joinpath("00-info.yaml").write_text(
        "facts:\n"
        "  - fid: fact-20260813-001\n"
        "    type: info\n"
        "    trust: confirmed\n"
        "    importance: medium\n"
        "    statement: 事实样本\n"
        "    summary: 样本\n"
        "    verified_at: '2026-08-13'\n"
        "    expiry: '2026-11-11'\n"
        "    entity_ids: [entity-demo]\n"
        "    status: active\n",
        encoding="utf-8",
    )
    facts_dir.joinpath("_index.yaml").write_text("facts_total: 1\nby_type: {info: 1}\n", encoding="utf-8")
    source_root = Path(__file__).parents[1] / "src"
    monkeypatch.setenv("PYTHONPATH", str(source_root))

    exit_code = main(
        ["documents", "run", "documents-weijian-facts-audit", "--json"],
        environ={
            "DOCUMENTS_CONTENT_ROOT": str(documents_root),
            "OMOSTATION_RUNTIME_STATE_ROOT": str(tmp_path / "state"),
            "PYTHONPATH": str(source_root),
        },
    )

    payload = json.loads(capsys.readouterr().out)
    evidence = json.loads(Path(payload["evidence_path"]).read_text(encoding="utf-8"))
    assert exit_code == 0
    assert evidence["owner_evidence"] == {
        "schema": "runtime.documents-facts-audit.evidence.v1",
        "status": "ok",
        "facts_total": 1,
        "by_type": {"info": 1},
        "error_count": 0,
        "warning_count": 0,
    }
    assert "stdout" not in evidence
    assert "statement" not in json.dumps(evidence, ensure_ascii=False)


def test_facts_evidence_projection_rejects_successful_malformed_owner_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    registry = JobRegistry()
    registry.register(
        replace(_spec(), evidence_projection="facts-audit-v1"),
        [sys.executable, "-c", "print('not-json')"],
    )
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()

    result = run_job(
        registry,
        "contract-check",
        state_root=tmp_path / "state",
        documents_root=documents_root,
    )

    assert result.exit_code == 74
    assert result.evidence_error == "facts-audit evidence must be a JSON object"
    assert result.evidence_path is not None
    evidence = json.loads(result.evidence_path.read_text(encoding="utf-8"))
    assert evidence["evidence_error"] == result.evidence_error
    assert "owner_evidence" not in evidence


def test_default_cli_registry_job_preserves_owner_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from runtime.documents_plane.cli import main

    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    documents_root = tmp_path / "Documents"
    registry_path = documents_root / "@公共/_control/L4-DOMAIN-REGISTRY.yaml"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("broken: [\n", encoding="utf-8")
    owner = tmp_path / "fake-l4-kernel"
    owner.write_text("#!/bin/sh\nprintf 'invalid registry\\n' >&2\nexit 2\n", encoding="utf-8")
    owner.chmod(0o755)

    exit_code = main(
        ["documents", "run", "l4-registry-list", "--json"],
        environ={
            "DOCUMENTS_CONTENT_ROOT": str(documents_root),
            "OMOSTATION_RUNTIME_STATE_ROOT": str(tmp_path / "state"),
            "L4_KERNEL_COMMAND": str(owner),
            "L4_DOMAIN_REGISTRY": str(registry_path),
        },
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "failed"
    assert payload["exit_code"] == 2
    assert payload["stderr"] == "invalid registry\n"
    assert payload["evidence_path"]


def test_default_cli_rejects_registry_path_outside_documents_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from runtime.documents_plane.cli import main

    documents_root = tmp_path / "Documents"
    documents_root.mkdir()
    outside_registry = tmp_path / "outside-registry.yaml"
    outside_registry.write_text("kind: registry\n", encoding="utf-8")

    exit_code = main(
        ["documents", "run", "l4-registry-list", "--json"],
        environ={
            "DOCUMENTS_CONTENT_ROOT": str(documents_root),
            "OMOSTATION_RUNTIME_STATE_ROOT": str(tmp_path / "state"),
            "L4_DOMAIN_REGISTRY": str(outside_registry),
        },
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "failed"
    assert "must be inside DOCUMENTS_CONTENT_ROOT" in payload["error"]
    assert not (tmp_path / "state").exists()


def test_default_cli_content_audit_delegates_documents_root_to_l4_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from runtime.documents_plane.cli import main

    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()
    owner = tmp_path / "fake-l4-kernel"
    owner.write_text(
        "#!/bin/sh\n"
        'test "$1" = content\n'
        'test "$2" = audit\n'
        'test "$3" = "$DOCUMENTS_CONTENT_ROOT"\n'
        'test "$4" = --json\n'
        "printf '%s\\n' '{\"ok\":false}'\n"
        "exit 1\n",
        encoding="utf-8",
    )
    owner.chmod(0o755)

    exit_code = main(
        ["documents", "run", "l4-content-audit", "--json"],
        environ={
            "DOCUMENTS_CONTENT_ROOT": str(documents_root),
            "OMOSTATION_RUNTIME_STATE_ROOT": str(tmp_path / "state"),
            "L4_KERNEL_COMMAND": str(owner),
        },
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["job_id"] == "l4-content-audit"
    assert payload["owner"] == "l4-kernel"
    assert payload["status"] == "failed"
    assert payload["stdout"] == '{"ok":false}\n'
    assert payload["evidence_path"]


def test_run_job_writes_metadata_only_evidence_under_state_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _state_root: command,
    )
    registry = JobRegistry()
    registry.register(_spec(), [sys.executable, "-c", "print('owner output')"])
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()
    state_root = tmp_path / "state"

    result = run_job(
        registry,
        "contract-check",
        state_root=state_root,
        documents_root=documents_root,
    )

    assert result.exit_code == 0
    assert result.stdout == "owner output\n"
    assert result.evidence_path == (state_root / "control/evidence/contract-check/evidence/contract-check.json")
    evidence = json.loads(result.evidence_path.read_text(encoding="utf-8"))
    assert evidence["job_id"] == "contract-check"
    assert "stdout" not in evidence
    assert "stderr" not in evidence


def test_evidence_symlink_is_refused_without_writing_documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _state_root: command,
    )
    registry = JobRegistry()
    registry.register(_spec(), [sys.executable, "-c", "pass"])
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()
    state_root = tmp_path / "state"
    target = documents_root / "stolen-evidence.json"
    evidence = state_root / "control" / "evidence" / "contract-check" / "evidence/contract-check.json"
    evidence.parent.mkdir(parents=True)
    evidence.symlink_to(target)

    result = run_job(
        registry,
        "contract-check",
        state_root=state_root,
        documents_root=documents_root,
    )

    assert result.exit_code == 74
    assert result.evidence_error
    assert not target.exists()


def test_evidence_directory_is_refused_without_replacing_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _state_root: command,
    )
    registry = JobRegistry()
    registry.register(_spec(), [sys.executable, "-c", "pass"])
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()
    state_root = tmp_path / "state"
    evidence = state_root / "control" / "evidence" / "contract-check" / "evidence/contract-check.json"
    evidence.mkdir(parents=True)

    result = run_job(registry, "contract-check", state_root=state_root, documents_root=documents_root)

    assert result.exit_code == 74
    assert result.evidence_error
    assert evidence.is_dir()


def test_evidence_failure_preserves_owner_failure_and_cli_json_stays_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from runtime.documents_plane.cli import main

    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _state_root: command,
    )
    monkeypatch.setattr(
        "runtime.documents_plane.jobs._persist_evidence",
        lambda *_args: (_ for _ in ()).throw(OSError("evidence unavailable")),
    )
    registry = JobRegistry()
    registry.register(_spec(), [sys.executable, "-c", "raise SystemExit(7)"])

    exit_code = main(
        ["documents", "run", "contract-check", "--json"],
        registry=registry,
        environ={
            "DOCUMENTS_CONTENT_ROOT": str(tmp_path / "Documents"),
            "OMOSTATION_RUNTIME_STATE_ROOT": str(tmp_path / "state"),
        },
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 7
    assert payload["exit_code"] == 7
    assert payload["evidence_error"]


def test_repeated_runs_use_distinct_work_roots_reported_by_owner_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    registry = JobRegistry()
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()
    script = """
import json
import os
from pathlib import Path

output = Path(os.environ['OMOSTATION_RUNTIME_STATE_ROOT'])
work_roots = {
    Path.cwd().parent,
    Path(os.environ['HOME']).parent,
    Path(os.environ['XDG_STATE_HOME']).parents[1],
}
if len(work_roots) != 1:
    raise SystemExit(9)
record = output / 'receipts' / 'contract-check.json'
previous = json.loads(record.read_text()) if record.exists() else []
record.write_text(json.dumps([*previous, str(work_roots.pop())]))
"""
    registry.register(_spec(), [sys.executable, "-c", script])
    state_root = tmp_path / "state"

    first = run_job(registry, "contract-check", state_root=state_root, documents_root=documents_root)
    second = run_job(registry, "contract-check", state_root=state_root, documents_root=documents_root)

    assert first.exit_code == 0
    assert second.exit_code == 0
    roots = json.loads(
        (state_root / "owner-output/contract-check/receipts/contract-check.json").read_text(encoding="utf-8")
    )
    assert len(roots) == 2
    assert roots[0] != roots[1]
    assert all(Path(root).parent == (state_root / "control/runs").resolve() for root in roots)
    assert list(documents_root.iterdir()) == []


def test_repeated_runs_atomically_replace_regular_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    registry = JobRegistry()
    registry.register(_spec(), [sys.executable, "-c", "pass"])
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()
    state_root = tmp_path / "state"

    first = run_job(registry, "contract-check", state_root=state_root, documents_root=documents_root)
    second = run_job(registry, "contract-check", state_root=state_root, documents_root=documents_root)

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert second.evidence_path is not None
    assert second.evidence_path.is_file()


def test_evidence_write_failure_removes_random_temporary_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runtime.documents_plane import jobs

    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    monkeypatch.setattr(
        jobs.os,
        "write",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    registry = JobRegistry()
    registry.register(_spec(), [sys.executable, "-c", "pass"])
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()
    state_root = tmp_path / "state"

    result = run_job(registry, "contract-check", state_root=state_root, documents_root=documents_root)

    evidence_parent = state_root / "control/evidence/contract-check/evidence"
    assert result.exit_code == 74
    assert result.evidence_error == "disk full"
    assert list(evidence_parent.iterdir()) == []


def test_evidence_fd_close_failure_returns_stable_io_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime.documents_plane import jobs

    original_close = jobs._PrivateLayout.close

    def close_then_fail(layout: jobs._PrivateLayout) -> None:
        original_close(layout)
        raise OSError("close failed")

    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    monkeypatch.setattr(jobs._PrivateLayout, "close", close_then_fail)
    registry = JobRegistry()
    registry.register(_spec(), [sys.executable, "-c", "pass"])
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()

    result = run_job(
        registry,
        "contract-check",
        state_root=tmp_path / "state",
        documents_root=documents_root,
    )

    assert result.exit_code == 74
    assert result.evidence_error == "close failed"


def test_private_layout_closes_evidence_fd_when_owner_layout_creation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runtime.documents_plane import jobs

    evidence_parent_fds: list[int] = []
    original_open_child = jobs._open_child_directory
    original_open_parent = jobs._open_relative_parent

    def open_child(parent_fd: int, name: str) -> int:
        if name == "owner-output":
            raise OSError("owner layout unavailable")
        return original_open_child(parent_fd, name)

    def open_parent(root_fd: int, relative: Path) -> tuple[int, str]:
        result = original_open_parent(root_fd, relative)
        evidence_parent_fds.append(result[0])
        return result

    monkeypatch.setattr(jobs, "_open_child_directory", open_child)
    monkeypatch.setattr(jobs, "_open_relative_parent", open_parent)
    registry = JobRegistry()
    registry.register(_spec(), [sys.executable, "-c", "pass"])
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()

    result = run_job(
        registry,
        "contract-check",
        state_root=tmp_path / "state",
        documents_root=documents_root,
    )

    assert result.exit_code == 74
    assert evidence_parent_fds
    with pytest.raises(OSError):
        jobs.os.fstat(evidence_parent_fds[-1])


@pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec is macOS-only")
def test_macos_repeated_owner_poison_cannot_reach_next_work_root_or_documents(
    tmp_path: Path,
) -> None:
    registry = JobRegistry()
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()
    state_root = tmp_path / "state"
    script = """
import json
import os
import shutil
from pathlib import Path

output = Path(os.environ['OMOSTATION_RUNTIME_STATE_ROOT'])
work = Path(os.environ['HOME']).parent
record = output / 'receipts' / 'contract-check.json'
previous = json.loads(record.read_text()) if record.exists() else []
record.write_text(json.dumps([*previous, str(work)]))
xdg = work / 'xdg'
shutil.rmtree(xdg)
xdg.symlink_to(Path(os.environ['DOCUMENTS_CONTENT_ROOT']), target_is_directory=True)
try:
    (xdg / 'forbidden.txt').write_text('forbidden')
except OSError:
    pass
"""
    registry.register(_spec(), [sys.executable, "-c", script])

    first = run_job(registry, "contract-check", state_root=state_root, documents_root=documents_root)
    second = run_job(registry, "contract-check", state_root=state_root, documents_root=documents_root)

    roots = json.loads(
        (state_root / "owner-output/contract-check/receipts/contract-check.json").read_text(encoding="utf-8")
    )
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert len(set(roots)) == 2
    assert list(documents_root.iterdir()) == []


@pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec is macOS-only")
def test_macos_owner_output_cannot_modify_control_or_documents(tmp_path: Path) -> None:
    registry = JobRegistry()
    script = """
import os
from pathlib import Path

output = Path(os.environ['OMOSTATION_RUNTIME_STATE_ROOT'])
blocked = []
for target in (output.parents[1] / 'control' / 'forbidden.txt', Path(os.environ['DOCUMENTS_CONTENT_ROOT']) / 'forbidden.txt'):
    try:
        target.write_text('forbidden', encoding='utf-8')
    except OSError:
        blocked.append(target)
(output / 'receipts' / 'contract-check.json').write_text('allowed', encoding='utf-8')
raise SystemExit(0 if len(blocked) == 2 else 1)
"""
    registry.register(_spec(), [sys.executable, "-c", script])
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()
    state_root = tmp_path / "state"

    result = run_job(
        registry,
        "contract-check",
        state_root=state_root,
        documents_root=documents_root,
    )

    assert result.exit_code == 0
    assert not (state_root / "control" / "forbidden.txt").exists()
    assert not (documents_root / "forbidden.txt").exists()
    assert (state_root / "owner-output/contract-check/receipts/contract-check.json").exists()


def test_documents_cli_runs_registered_job_as_json_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from runtime.documents_plane.cli import main

    registry = JobRegistry()
    registry.register(_spec(), [sys.executable, "-c", "raise SystemExit(99)"])

    exit_code = main(
        ["documents", "run", "contract-check", "--dry-run", "--json"],
        registry=registry,
        environ={
            "DOCUMENTS_CONTENT_ROOT": str(tmp_path / "Documents"),
            "OMOSTATION_RUNTIME_STATE_ROOT": str(tmp_path / "state"),
        },
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert not (tmp_path / "state").exists()


def test_default_registry_loads_exact_model_freshness_binding(tmp_path: Path) -> None:
    from runtime.documents_plane.cli import _default_registry

    environ = _model_freshness_binding_environ(tmp_path)
    registry_path = Path(environ["DOCUMENTS_CONTENT_ROOT"]) / "@公共/_control/L4-DOMAIN-REGISTRY.yaml"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("kind: registry\n", encoding="utf-8")

    spec, command = _default_registry(environ).resolve("documents-weijian-model-freshness")

    assert spec == JobSpec(
        job_id="documents-weijian-model-freshness",
        reads=(
            "@工作文档/卫健委/_entities/facts.md",
            "@工作文档/卫健委/_entities/models",
        ),
        writes=(),
        owner="runtime-control",
        schedule="manual",
        timeout=30,
        evidence_path="documents-weijian-model-freshness.json",
        fail_closed=True,
        evidence_projection="model-freshness-v1",
    )
    assert command[-2:] == ("--domain-relative", "@工作文档/卫健委")


@pytest.mark.parametrize(
    ("facts_reviewed", "model_reviewed", "expected_exit", "expected_status"),
    [
        ("2026-08-13", "2026-08-13", 0, "ok"),
        ("2026-08-13", "2026-08-12", 1, "attention"),
    ],
)
def test_model_freshness_job_persists_only_bounded_owner_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    facts_reviewed: str,
    model_reviewed: str,
    expected_exit: int,
    expected_status: str,
) -> None:
    from runtime.documents_plane.cli import main

    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    environ = _model_freshness_binding_environ(tmp_path)
    documents_root = Path(environ["DOCUMENTS_CONTENT_ROOT"])
    _write_model_freshness_fixture(
        documents_root,
        facts_reviewed=facts_reviewed,
        model_reviewed=model_reviewed,
    )
    registry_path = documents_root / "@公共/_control/L4-DOMAIN-REGISTRY.yaml"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("kind: registry\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", environ["PYTHONPATH"])

    exit_code = main(
        ["documents", "run", "documents-weijian-model-freshness", "--json"],
        environ=environ,
    )

    result = json.loads(capsys.readouterr().out)
    receipt = json.loads(Path(result["evidence_path"]).read_text(encoding="utf-8"))
    checked_on = receipt["owner_evidence"]["checked_on"]
    assert date.fromisoformat(checked_on).isoformat() == checked_on
    assert exit_code == expected_exit
    assert receipt["exit_code"] == expected_exit
    assert receipt["evidence_error"] is None
    assert receipt["owner_evidence"] == {
        "schema": "runtime.documents-model-freshness.evidence.v1",
        "status": expected_status,
        "checked_on": checked_on,
        "facts_last_reviewed": facts_reviewed,
        "model_markdown_count": 1,
        "fresh_model_count": int(expected_status == "ok"),
        "stale_model_count": int(expected_status == "attention"),
        "invalid_reviewed_count": 0,
        "unreadable_regular_file_count": 0,
        "error": None,
    }
    encoded_receipt = json.dumps(receipt, ensure_ascii=False)
    assert "stdout" not in receipt
    assert "@工作文档" not in encoded_receipt
    assert "fixture-private-model.md" not in encoded_receipt
    assert "fixture private model body" not in encoded_receipt


def test_model_freshness_unavailable_exit_two_still_persists_valid_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from runtime.documents_plane.cli import main

    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    environ = _model_freshness_binding_environ(tmp_path)
    documents_root = Path(environ["DOCUMENTS_CONTENT_ROOT"])
    models = documents_root / "@工作文档" / "卫健委" / "_entities" / "models"
    models.mkdir(parents=True)
    models.joinpath("fixture-private-model.md").write_text(
        "last-reviewed: 2026-08-13\nfixture private model body\n",
        encoding="utf-8",
    )
    registry_path = documents_root / "@公共/_control/L4-DOMAIN-REGISTRY.yaml"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("kind: registry\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", environ["PYTHONPATH"])

    exit_code = main(
        ["documents", "run", "documents-weijian-model-freshness", "--json"],
        environ=environ,
    )

    result = json.loads(capsys.readouterr().out)
    receipt = json.loads(Path(result["evidence_path"]).read_text(encoding="utf-8"))
    assert exit_code == 2
    assert receipt["exit_code"] == 2
    assert receipt["evidence_error"] is None
    assert receipt["owner_evidence"]["status"] == "unavailable"
    assert receipt["owner_evidence"]["error"] == "facts_file_missing"
    encoded_receipt = json.dumps(receipt, ensure_ascii=False)
    assert "@工作文档" not in encoded_receipt
    assert "fixture-private-model.md" not in encoded_receipt
    assert "fixture private model body" not in encoded_receipt


def test_model_freshness_projection_rejects_successful_malformed_owner_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    registry = JobRegistry()
    registry.register(
        replace(
            _spec(),
            writes=(),
            evidence_projection="model-freshness-v1",
        ),
        [
            sys.executable,
            "-c",
            "import json; print(json.dumps({'schema': 'runtime.documents-model-freshness.v1', 'status': 'ok'}))",
        ],
    )
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()

    result = run_job(
        registry,
        "contract-check",
        state_root=tmp_path / "state",
        documents_root=documents_root,
    )

    assert result.exit_code == 74
    assert result.evidence_error == "model-freshness evidence has an invalid schema"
    assert result.evidence_path is not None
    receipt = json.loads(result.evidence_path.read_text(encoding="utf-8"))
    assert receipt["exit_code"] == 74
    assert receipt["evidence_error"] == result.evidence_error
    assert "owner_evidence" not in receipt


@pytest.mark.parametrize(
    "payload",
    [
        {
            "schema": "runtime.documents-model-freshness.v1",
            "status": "unavailable",
            "checked_on": "2026-08-14",
            "facts_last_reviewed": "2026-08-13",
            "model_markdown_count": 1,
            "fresh_model_count": 0,
            "stale_model_count": 0,
            "invalid_reviewed_count": 0,
            "unreadable_regular_file_count": 0,
            "error": "facts_file_missing",
        },
        {
            "schema": "runtime.documents-model-freshness.v1",
            "status": "unavailable",
            "checked_on": "2026-08-14",
            "facts_last_reviewed": None,
            "model_markdown_count": 0,
            "fresh_model_count": 0,
            "stale_model_count": 0,
            "invalid_reviewed_count": 0,
            "unreadable_regular_file_count": 0,
            "error": "models_directory_missing",
        },
        {
            "schema": "runtime.documents-model-freshness.v1",
            "status": "unavailable",
            "checked_on": "2026-08-14",
            "facts_last_reviewed": "2026-08-13",
            "model_markdown_count": 0,
            "fresh_model_count": 0,
            "stale_model_count": 0,
            "invalid_reviewed_count": 0,
            "unreadable_regular_file_count": 0,
            "error": "model_file_not_regular",
        },
        {
            "schema": "runtime.documents-model-freshness.v1",
            "status": "unavailable",
            "checked_on": "2026-08-14",
            "facts_last_reviewed": "2026-08-13",
            "model_markdown_count": 1,
            "fresh_model_count": 0,
            "stale_model_count": 0,
            "invalid_reviewed_count": 0,
            "unreadable_regular_file_count": 0,
            "error": "model_file_unreadable",
        },
        {
            "schema": "runtime.documents-model-freshness.v1",
            "status": "unavailable",
            "checked_on": "2026-08-14",
            "facts_last_reviewed": "2026-08-13",
            "model_markdown_count": 1,
            "fresh_model_count": 0,
            "stale_model_count": 0,
            "invalid_reviewed_count": 0,
            "unreadable_regular_file_count": 0,
            "error": "model_last_reviewed_invalid",
        },
    ],
)
def test_model_freshness_projection_rejects_unavailable_error_state_conflicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: dict[str, object]
) -> None:
    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    registry = JobRegistry()
    registry.register(
        replace(_spec(), writes=(), evidence_projection="model-freshness-v1"),
        [
            sys.executable,
            "-c",
            f"import json; print(json.dumps({payload!r}))",
        ],
    )
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()

    result = run_job(
        registry,
        "contract-check",
        state_root=tmp_path / "state",
        documents_root=documents_root,
    )

    assert result.exit_code == 74
    assert result.evidence_error == "model-freshness evidence has an invalid schema"
    assert result.evidence_path is not None
    receipt = json.loads(result.evidence_path.read_text(encoding="utf-8"))
    assert receipt["exit_code"] == 74
    assert receipt["evidence_error"] == result.evidence_error
    assert "owner_evidence" not in receipt


def _write_sanyi_documents(root: Path, *, dashboard: str = "2026-08-05", latest: str = "2026-08-13") -> Path:
    documents_root = root / "Documents"
    domain = documents_root / "@工作文档" / "卫健委"
    dashboard_path = domain / "_control" / "三医态势仪表盘.md"
    facts_path = domain / "_entities" / "facts" / "01-progress.yaml"
    dashboard_path.parent.mkdir(parents=True)
    facts_path.parent.mkdir(parents=True)
    dashboard_path.write_text(
        f"---\nlast-reviewed: '{dashboard}'\n---\n# 三医态势\n",
        encoding="utf-8",
    )
    facts_path.write_text(
        "facts:\n  - fid: fact-private\n    statement: 不得进入收据\n"
        f"    entity_ids: [proj-syld]\n    verified_at: '{latest}'\n",
        encoding="utf-8",
    )
    return documents_root


def _sanyi_environ(root: Path, *, documents_root: Path | None = None) -> dict[str, str]:
    documents = documents_root or _write_sanyi_documents(root)
    binding_path = root / "documents-domain-projects.yaml"
    binding_path.write_text(
        json.dumps(
            {
                "runtime_jobs": [
                    {
                        "id": "documents-weijian-controller-shadow",
                        "domain_id": "work-weijian",
                        "owner": "runtime-control",
                        "action": "shadow_legacy_controller",
                        "schedule": "manual",
                        "timeout_seconds": 30,
                        "reads": [
                            "@工作文档/卫健委/_control",
                            "@工作文档/卫健委/_entities",
                            "@工作文档/卫健委/_meta",
                            "@工作文档/卫健委/_runtime",
                            "@工作文档/卫健委/_storage",
                            "@工作文档/卫健委/_knowledge",
                        ],
                        "writes": [],
                        "evidence_relative_path": "control/evidence/documents-weijian-controller-shadow/documents-weijian-controller-shadow.json",
                        "evidence_schema": "runtime.documents-controller-shadow.evidence.v2",
                        "fail_closed": True,
                    },
                    {
                        "id": "documents-weijian-sanyi-status-audit",
                        "domain_id": "work-weijian",
                        "owner": "runtime-control",
                        "action": "audit_sanyi_status_consistency",
                        "schedule": "manual",
                        "timeout_seconds": 30,
                        "reads": [
                            "@工作文档/卫健委/_control/三医态势仪表盘.md",
                            "@工作文档/卫健委/_entities/facts/01-progress.yaml",
                        ],
                        "scope_entity_ids": [
                            "proj-syld",
                            "proj-jingbao",
                            "proj-emr-quality",
                        ],
                        "writes": [],
                        "evidence_relative_path": "control/evidence/documents-weijian-sanyi-status-audit/documents-weijian-sanyi-status-audit.json",
                        "evidence_schema": "runtime.documents-sanyi-status-consistency.evidence.v1",
                        "fail_closed": True,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {
        "DOCUMENTS_CONTENT_ROOT": str(documents),
        "OMOSTATION_RUNTIME_STATE_ROOT": str(root / "state"),
        "DOCUMENTS_DOMAIN_PROJECTS_REGISTRY": str(binding_path),
    }


@pytest.mark.parametrize("mutation", ["missing", "drift"])
def test_default_registry_fails_closed_when_controller_shadow_binding_is_invalid(tmp_path: Path, mutation: str) -> None:
    from runtime.documents_plane.cli import _default_registry
    from runtime.documents_plane.paths import DocumentsPlanePathError

    environ = _sanyi_environ(tmp_path)
    binding_path = Path(environ["DOCUMENTS_DOMAIN_PROJECTS_REGISTRY"])
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    if mutation == "missing":
        binding["runtime_jobs"] = binding["runtime_jobs"][1:]
    else:
        binding["runtime_jobs"][0]["reads"] = []
    binding_path.write_text(json.dumps(binding), encoding="utf-8")

    with pytest.raises(DocumentsPlanePathError, match="controller shadow job"):
        _default_registry(environ)


def test_default_registry_registers_controller_model_and_sanyi_bindings(
    tmp_path: Path,
) -> None:
    from runtime.documents_plane.cli import _default_registry

    environ = _model_freshness_binding_environ(tmp_path)
    binding_path = Path(environ["DOCUMENTS_DOMAIN_PROJECTS_REGISTRY"])
    binding_path.write_text(
        binding_path.read_text(encoding="utf-8")
        + """  - id: documents-weijian-sanyi-status-audit
    domain_id: work-weijian
    owner: runtime-control
    action: audit_sanyi_status_consistency
    schedule: manual
    timeout_seconds: 30
    reads:
      - "@工作文档/卫健委/_control/三医态势仪表盘.md"
      - "@工作文档/卫健委/_entities/facts/01-progress.yaml"
    scope_entity_ids:
      - proj-syld
      - proj-jingbao
      - proj-emr-quality
    writes: []
    evidence_relative_path: control/evidence/documents-weijian-sanyi-status-audit/documents-weijian-sanyi-status-audit.json
    evidence_schema: runtime.documents-sanyi-status-consistency.evidence.v1
    fail_closed: true
""",
        encoding="utf-8",
    )

    registry = _default_registry(environ)

    assert registry.resolve("documents-weijian-controller-shadow")[0].owner == "runtime-control"
    assert registry.resolve("documents-weijian-model-freshness")[0].owner == "runtime-control"
    assert registry.resolve("documents-weijian-sanyi-status-audit")[0].owner == "runtime-control"


def _documents_digest(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple((str(path.relative_to(root)), path.read_bytes()) for path in sorted(root.rglob("*")) if path.is_file())


def test_sanyi_status_job_persists_bounded_attention_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from runtime.documents_plane.cli import main

    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[1] / "src"))
    environ = _sanyi_environ(tmp_path)
    assert (
        main(
            ["documents", "run", "documents-weijian-sanyi-status-audit", "--json"],
            environ=environ,
        )
        == 1
    )
    cli_payload = json.loads(capsys.readouterr().out)
    serialized_cli = json.dumps(cli_payload, ensure_ascii=False)
    assert "evidence_path" not in cli_payload
    assert str(tmp_path) not in serialized_cli
    assert "01-progress.yaml" not in serialized_cli
    assert "三医态势仪表盘.md" not in serialized_cli
    assert "fact-private" not in serialized_cli
    assert "不得进入收据" not in serialized_cli
    receipt_path = (
        Path(environ["OMOSTATION_RUNTIME_STATE_ROOT"])
        / "control/evidence/documents-weijian-sanyi-status-audit/documents-weijian-sanyi-status-audit.json"
    )
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["owner_evidence"]["status"] == "attention"
    assert receipt["owner_evidence"]["schema"] == ("runtime.documents-sanyi-status-consistency.evidence.v1")
    assert "statement" not in json.dumps(receipt, ensure_ascii=False)


def test_sanyi_status_dry_run_and_real_run_never_write_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runtime.documents_plane.cli import main

    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[1] / "src"))
    documents_root = _write_sanyi_documents(tmp_path)
    environ = _sanyi_environ(tmp_path, documents_root=documents_root)
    before = _documents_digest(documents_root)
    assert (
        main(
            [
                "documents",
                "run",
                "documents-weijian-sanyi-status-audit",
                "--dry-run",
                "--json",
            ],
            environ=environ,
        )
        == 0
    )
    assert main(
        ["documents", "run", "documents-weijian-sanyi-status-audit", "--json"],
        environ=environ,
    ) in {0, 1, 2}
    assert _documents_digest(documents_root) == before


def test_sanyi_text_cli_redacts_runtime_state_io_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from runtime.documents_plane.cli import main

    environ = _sanyi_environ(tmp_path)
    environ["OMOSTATION_RUNTIME_STATE_ROOT"] = "/dev/null"
    assert (
        main(
            ["documents", "run", "documents-weijian-sanyi-status-audit"],
            environ=environ,
        )
        == 74
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == "documents-weijian-sanyi-status-audit: runtime_error\n"
    assert "/dev/null" not in captured.out
    assert "File exists" not in captured.out


@pytest.mark.parametrize(
    ("arguments", "json_output"),
    [
        (
            [
                "documents",
                "run",
                "documents-weijian-sanyi-status-audit",
                "--untrusted",
                "/private/secret-fid.yaml",
            ],
            False,
        ),
        (
            [
                "documents",
                "run",
                "--untrusted",
                "/private/secret-fid.yaml",
                "documents-weijian-sanyi-status-audit",
            ],
            False,
        ),
        (
            [
                "documents",
                "--untrusted",
                "/private/secret-fid.yaml",
                "run",
                "documents-weijian-sanyi-status-audit",
            ],
            False,
        ),
        (
            [
                "documents",
                "run",
                "documents-weijian-sanyi-status-audit",
                "--json",
                "--untrusted",
                "/private/secret-fid.yaml",
            ],
            True,
        ),
    ],
)
def test_documents_cli_redacts_cr08_argument_parse_failures(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    json_output: bool,
) -> None:
    from runtime.documents_plane.cli import main

    exit_code = main(arguments, environ=_sanyi_environ(tmp_path))

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.err == ""
    assert "/private/secret-fid.yaml" not in captured.out
    assert "/private/secret-fid.yaml" not in captured.err
    if json_output:
        payload = json.loads(captured.out)
        assert payload["status"] == "unavailable"
        assert payload["error"] == "arguments_invalid"
    else:
        assert captured.out == "documents-weijian-sanyi-status-audit: arguments_invalid\n"


def test_sanyi_binding_rejects_unknown_or_reordered_contract_values(
    tmp_path: Path,
) -> None:
    from runtime.documents_plane.cli import _sanyi_status_job_spec
    from runtime.documents_plane.paths import DocumentsPlanePathError

    environ = _sanyi_environ(tmp_path)
    binding_path = Path(environ["DOCUMENTS_DOMAIN_PROJECTS_REGISTRY"])
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    sanyi_job = next(job for job in binding["runtime_jobs"] if job["id"] == "documents-weijian-sanyi-status-audit")
    sanyi_job["scope_entity_ids"].reverse()
    sanyi_job["unexpected"] = True
    binding_path.write_text(json.dumps(binding), encoding="utf-8")
    with pytest.raises(DocumentsPlanePathError, match="invalid contract"):
        _sanyi_status_job_spec(environ)


def test_sanyi_receipt_rejects_malformed_owner_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime.documents_plane.cli import _sanyi_status_job_spec

    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    registry = JobRegistry()
    registry.register(
        _sanyi_status_job_spec(_sanyi_environ(tmp_path)),
        [sys.executable, "-c", "print('{}')"],
    )
    result = run_job(
        registry,
        "documents-weijian-sanyi-status-audit",
        state_root=tmp_path / "state",
        documents_root=tmp_path / "Documents",
    )
    assert result.exit_code == 74
    assert result.evidence_error == "sanyi-status evidence has an invalid schema"
