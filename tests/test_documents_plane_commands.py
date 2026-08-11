from __future__ import annotations

import sys

from runtime.documents_plane.commands import run_owner_command


def test_owner_command_preserves_stdout_stderr_and_nonzero_exit() -> None:
    result = run_owner_command(
        [
            sys.executable,
            "-c",
            "import sys; print('out'); print('err', file=sys.stderr); raise SystemExit(7)",
        ],
        timeout=1,
    )

    assert result.exit_code == 7
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"
    assert result.timed_out is False


def test_owner_command_reports_timeout_without_raising() -> None:
    result = run_owner_command(
        [sys.executable, "-c", "import time; time.sleep(1)"], timeout=0.01
    )

    assert result.exit_code == 124
    assert result.timed_out is True
    assert result.stderr
