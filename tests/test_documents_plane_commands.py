from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from runtime.documents_plane.commands import run_owner_command


def _disable_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda command, _state_root: command,
    )


def test_owner_command_preserves_stdout_stderr_and_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _disable_sandbox(monkeypatch)
    result = run_owner_command(
        [
            sys.executable,
            "-c",
            "import sys; print('out'); print('err', file=sys.stderr); raise SystemExit(7)",
        ],
        timeout=1,
        state_root=tmp_path / "state",
    )

    assert result.exit_code == 7
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"
    assert result.timed_out is False


def test_owner_command_reports_timeout_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _disable_sandbox(monkeypatch)
    result = run_owner_command(
        [sys.executable, "-c", "import time; time.sleep(1)"],
        timeout=0.01,
        state_root=tmp_path / "state",
    )

    assert result.exit_code == 124
    assert result.timed_out is True
    assert result.stderr


def test_sandbox_unavailable_fails_closed_without_executing_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "owner-ran"
    monkeypatch.setattr(
        "runtime.documents_plane.commands._sandbox_argv",
        lambda _command, _state_root: None,
    )

    result = run_owner_command(
        [
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).touch()",
        ],
        timeout=1,
        state_root=tmp_path / "state",
    )

    assert result.exit_code == 125
    assert result.timed_out is False
    assert "isolation unavailable" in result.stderr
    assert not marker.exists()


def test_owner_refuses_documents_root_nested_in_state_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _disable_sandbox(monkeypatch)
    state_root = tmp_path / "state"
    marker = state_root / "owner-ran"

    with pytest.raises(ValueError, match="overlap"):
        run_owner_command(
            [
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).touch()",
            ],
            timeout=1,
            state_root=state_root,
            documents_root=state_root / "Documents",
        )

    assert not marker.exists()


def test_owner_runs_with_cwd_and_write_related_env_inside_state_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _disable_sandbox(monkeypatch)
    state_root = tmp_path / "state"
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()
    script = """
import json
import os
from pathlib import Path

state = Path(os.environ['OMOSTATION_RUNTIME_STATE_ROOT'])
payload = {name: os.environ[name] for name in ('HOME', 'TMPDIR', 'XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'DOCUMENTS_CONTENT_ROOT')}
payload['cwd'] = os.getcwd()
(state / 'environment.json').write_text(json.dumps(payload), encoding='utf-8')
"""

    result = run_owner_command(
        [sys.executable, "-c", script],
        timeout=1,
        state_root=state_root,
        documents_root=documents_root,
    )

    assert result.exit_code == 0
    payload = json.loads((state_root / "environment.json").read_text(encoding="utf-8"))
    assert payload.pop("DOCUMENTS_CONTENT_ROOT") == str(documents_root.resolve())
    for value in payload.values():
        assert Path(value).resolve().is_relative_to(state_root.resolve())


def test_timeout_kills_entire_owner_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _disable_sandbox(monkeypatch)
    state_root = tmp_path / "state"
    delayed_write = state_root / "late-write.txt"
    child = (
        "import sys, time; from pathlib import Path; time.sleep(0.3); "
        "Path(sys.argv[1]).write_text('late', encoding='utf-8')"
    )
    parent = (
        "import subprocess, sys, time; subprocess.Popen("
        f"[sys.executable, '-c', {child!r}, {str(delayed_write)!r}]); time.sleep(10)"
    )

    result = run_owner_command(
        [sys.executable, "-c", parent], timeout=0.05, state_root=state_root
    )
    time.sleep(0.5)

    assert result.exit_code == 124
    assert result.timed_out is True
    assert not delayed_write.exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec is macOS-only")
def test_macos_sandbox_denies_documents_write_and_allows_state_write(
    tmp_path: Path,
) -> None:
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()
    state_root = tmp_path / "state"
    documents_write = documents_root / "forbidden.txt"
    state_write = state_root / "owner-state.txt"
    script = f"""
from pathlib import Path

blocked = False
try:
    Path({str(documents_write)!r}).write_text('forbidden', encoding='utf-8')
except OSError:
    blocked = True
Path({str(state_write)!r}).write_text('allowed', encoding='utf-8')
raise SystemExit(0 if blocked else 1)
"""

    result = run_owner_command(
        [sys.executable, "-c", script], timeout=1, state_root=state_root
    )

    assert result.exit_code == 0
    assert not documents_write.exists()
    assert state_write.read_text(encoding="utf-8") == "allowed"
