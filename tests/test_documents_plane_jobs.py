from __future__ import annotations

import json
import shlex
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
        "printf '{\\\"ok\\\":true}\\n'\n",
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
    owner.write_text(
        "#!/bin/sh\nprintf 'invalid registry\\n' >&2\nexit 2\n", encoding="utf-8"
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
        "printf '{\\\"ok\\\":false}\\n'\n"
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


def test_evidence_directory_is_refused_without_replacing_it(
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
    evidence = (
        state_root
        / "control"
        / "evidence"
        / "contract-check"
        / "evidence/contract-check.json"
    )
    evidence.mkdir(parents=True)

    result = run_job(
        registry, "contract-check", state_root=state_root, documents_root=documents_root
    )

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

    first = run_job(
        registry, "contract-check", state_root=state_root, documents_root=documents_root
    )
    second = run_job(
        registry, "contract-check", state_root=state_root, documents_root=documents_root
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    roots = json.loads(
        (
            state_root / "owner-output/contract-check/receipts/contract-check.json"
        ).read_text(encoding="utf-8")
    )
    assert len(roots) == 2
    assert roots[0] != roots[1]
    assert all(
        Path(root).parent == (state_root / "control/runs").resolve() for root in roots
    )
    assert list(documents_root.iterdir()) == []


def test_repeated_runs_atomically_replace_regular_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _roots: command,
    )
    registry = JobRegistry()
    registry.register(_spec(), [sys.executable, "-c", "pass"])
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()
    state_root = tmp_path / "state"

    first = run_job(
        registry, "contract-check", state_root=state_root, documents_root=documents_root
    )
    second = run_job(
        registry, "contract-check", state_root=state_root, documents_root=documents_root
    )

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

    result = run_job(
        registry, "contract-check", state_root=state_root, documents_root=documents_root
    )

    evidence_parent = state_root / "control/evidence/contract-check/evidence"
    assert result.exit_code == 74
    assert result.evidence_error == "disk full"
    assert list(evidence_parent.iterdir()) == []


def test_evidence_fd_close_failure_returns_stable_io_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    first = run_job(
        registry, "contract-check", state_root=state_root, documents_root=documents_root
    )
    second = run_job(
        registry, "contract-check", state_root=state_root, documents_root=documents_root
    )

    roots = json.loads(
        (
            state_root / "owner-output/contract-check/receipts/contract-check.json"
        ).read_text(encoding="utf-8")
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
