from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
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
    assert result.evidence_path == (
        state_root / "control/evidence/contract-check/evidence/contract-check.json"
    )
    evidence = json.loads(result.evidence_path.read_text(encoding="utf-8"))
    assert evidence["job_id"] == "contract-check"
    assert "stdout" not in evidence
    assert "stderr" not in evidence


def test_evidence_symlink_is_refused_without_writing_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    evidence = (
        state_root
        / "control"
        / "evidence"
        / "contract-check"
        / "evidence/contract-check.json"
    )
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
    assert (
        state_root / "owner-output/contract-check/receipts/contract-check.json"
    ).exists()


def test_documents_cli_runs_registered_job_as_json_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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
