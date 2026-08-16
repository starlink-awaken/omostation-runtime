from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


def _domain(documents_root: Path) -> Path:
    domain = documents_root / "@工作文档" / "卫健委"
    for relative_path in (
        "_storage/01-Inbox/inbox.md",
        "_knowledge/guide.md",
        "_entities/entities/entity.md",
        "_control/STATUS.md",
    ):
        path = domain / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative_path, encoding="utf-8")
    inbox = documents_root / "_inbox" / "incoming.md"
    inbox.parent.mkdir(parents=True)
    inbox.write_text("incoming", encoding="utf-8")
    return domain


def test_kems_check_keeps_baseline_outside_documents_and_reports_changes(
    tmp_path: Path,
) -> None:
    from runtime.documents_plane.kems import check_kems

    documents_root = tmp_path / "Documents"
    domain = _domain(documents_root)
    state_path = tmp_path / "runtime" / "kems" / "weijian-check.json"

    initial = check_kems(
        domain, extra_inbox=documents_root / "_inbox", state_path=state_path
    )

    assert initial.status == "ok"
    assert initial.baseline == "initialized"
    assert initial.changed_scopes == ()
    assert state_path.is_file()
    assert not (domain / "_control" / ".kems_check_state.json").exists()

    control = domain / "_control" / "STATUS.md"
    control.write_text("changed", encoding="utf-8")
    changed = check_kems(
        domain, extra_inbox=documents_root / "_inbox", state_path=state_path
    )

    assert changed.status == "changed"
    assert changed.baseline == "existing"
    assert changed.changed_scopes == ("control",)
    assert not (domain / "_control" / ".kems_check_state.json").exists()


def test_kems_check_rejects_missing_domain_without_writing_a_baseline(
    tmp_path: Path,
) -> None:
    from runtime.documents_plane.kems import check_kems

    state_path = tmp_path / "runtime" / "kems" / "weijian-check.json"

    with pytest.raises(ValueError, match="domain root is missing"):
        check_kems(
            tmp_path / "Documents" / "@工作文档" / "卫健委",
            extra_inbox=None,
            state_path=state_path,
        )

    assert not state_path.exists()


def test_default_cli_runs_weijian_kems_check_with_runtime_only_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from runtime.documents_plane.cli import main

    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    documents_root = tmp_path / "Documents"
    domain = _domain(documents_root)
    source_root = Path(__file__).parents[1] / "src"
    monkeypatch.setenv("PYTHONPATH", str(source_root))

    initial_code = main(
        ["documents", "run", "documents-weijian-kems-check", "--json"],
        environ={
            "DOCUMENTS_CONTENT_ROOT": str(documents_root),
            "OMOSTATION_RUNTIME_STATE_ROOT": str(tmp_path / "state"),
            "PYTHONPATH": str(source_root),
        },
    )

    initial = json.loads(capsys.readouterr().out)
    assert initial_code == 0
    assert initial["job_id"] == "documents-weijian-kems-check"
    assert initial["owner"] == "runtime-kems"
    assert json.loads(initial["stdout"]) == {
        "baseline": "initialized",
        "changed_scopes": [],
        "schema": "runtime.documents-kems-check.v1",
        "status": "ok",
    }
    assert not (domain / "_control" / ".kems_check_state.json").exists()
    assert (
        tmp_path / "state" / "owner-output" / "documents-weijian-kems-check" / "kems"
    ).is_dir()

    (domain / "_control" / "STATUS.md").write_text("changed", encoding="utf-8")
    changed_code = main(
        ["documents", "run", "documents-weijian-kems-check", "--json"],
        environ={
            "DOCUMENTS_CONTENT_ROOT": str(documents_root),
            "OMOSTATION_RUNTIME_STATE_ROOT": str(tmp_path / "state"),
            "PYTHONPATH": str(source_root),
        },
    )

    changed = json.loads(capsys.readouterr().out)
    receipt = json.loads(Path(changed["evidence_path"]).read_text(encoding="utf-8"))
    assert changed_code == 1
    assert json.loads(changed["stdout"])["changed_scopes"] == ["control"]
    assert receipt["owner_evidence"] == {
        "baseline": "existing",
        "changed_scope_count": 1,
        "schema": "runtime.documents-kems-check.evidence.v1",
        "status": "changed",
    }
    assert "STATUS.md" not in json.dumps(receipt, ensure_ascii=False)


@pytest.mark.parametrize("changed_scopes", [["unknown"], ["control", "control"]])
def test_kems_receipt_rejects_unbounded_changed_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_scopes: list[str]
) -> None:
    from runtime.documents_plane.jobs import JobRegistry, JobSpec, run_job

    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    registry = JobRegistry()
    registry.register(
        JobSpec(
            job_id="kems-check",
            reads=("domain",),
            writes=(),
            owner="runtime-kems",
            schedule="manual",
            timeout=1,
            evidence_path="kems-check.json",
            fail_closed=True,
            evidence_projection="kems-check-v1",
        ),
        [
            sys.executable,
            "-c",
            (
                "import json; print(json.dumps({"
                "'schema': 'runtime.documents-kems-check.v1', "
                "'status': 'changed', 'baseline': 'existing', "
                f"'changed_scopes': {changed_scopes!r}}}))"
            ),
        ],
    )
    documents_root = tmp_path / "Documents"
    (documents_root / "domain").mkdir(parents=True)

    result = run_job(
        registry,
        "kems-check",
        documents_root=documents_root,
        state_root=tmp_path / "state",
    )

    assert result.exit_code == 74
    assert result.evidence_error == "KEMS check evidence has an invalid schema"
