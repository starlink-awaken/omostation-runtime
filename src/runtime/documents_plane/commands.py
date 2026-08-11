"""Narrow, isolated subprocess adapter for explicitly registered Documents jobs."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .paths import require_disjoint_roots

_ISOLATION_UNAVAILABLE_EXIT = 125


@dataclass(frozen=True)
class CommandResult:
    """Stable, lossless process outcome returned to the Runtime adapter."""

    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


def normalize_argv(argv: Sequence[str]) -> tuple[str, ...]:
    """Accept only a non-empty argv list; shell strings are intentionally refused."""
    if (
        isinstance(argv, str)
        or not argv
        or not all(isinstance(value, str) and value for value in argv)
    ):
        raise ValueError("owner command must be a non-empty argv list of strings")
    return tuple(argv)


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


def _sbpl_quote(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


def _sandbox_argv(command: tuple[str, ...], state_root: Path) -> tuple[str, ...] | None:
    """Build the macOS-only write-restricted argv, or fail closed elsewhere."""
    if sys.platform != "darwin":
        return None
    sandbox_exec = shutil.which("sandbox-exec")
    if sandbox_exec is None:
        return None
    profile = "\n".join(
        (
            "(version 1)",
            "(allow default)",
            "(deny file-write*)",
            f'(allow file-write* (subpath "{_sbpl_quote(state_root)}"))',
        )
    )
    return (sandbox_exec, "-p", profile, *command)


def _execution_environment(
    state_root: Path, documents_root: Path, environ: Mapping[str, str] | None
) -> tuple[Path, dict[str, str]]:
    """Make every conventional runtime write location live below state_root."""
    state = state_root.resolve()
    directories = {
        "home": state / "home",
        "work": state / "work",
        "tmp": state / "tmp",
        "cache": state / "xdg" / "cache",
        "config": state / "xdg" / "config",
        "xdg_state": state / "xdg" / "state",
    }
    for directory in directories.values():
        directory.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ if environ is None else environ)
    environment.pop("PYTHONPYCACHEPREFIX", None)
    environment.update(
        {
            "HOME": str(directories["home"]),
            "TMPDIR": str(directories["tmp"]),
            "TMP": str(directories["tmp"]),
            "TEMP": str(directories["tmp"]),
            "XDG_CACHE_HOME": str(directories["cache"]),
            "XDG_CONFIG_HOME": str(directories["config"]),
            "XDG_STATE_HOME": str(directories["xdg_state"]),
            "DOCUMENTS_CONTENT_ROOT": str(documents_root),
            "OMOSTATION_RUNTIME_STATE_ROOT": str(state),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return directories["work"], environment


def _timeout_result(
    process: subprocess.Popen[str], *, command: tuple[str, ...], timeout: float
) -> CommandResult:
    """Kill the session/process-group, then reap it and preserve captured output."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        process.kill()
    stdout, stderr = process.communicate()
    if stderr and not stderr.endswith("\n"):
        stderr += "\n"
    return CommandResult(
        argv=command,
        exit_code=124,
        stdout=stdout,
        stderr=f"{stderr}owner command timed out after {timeout:g}s\n",
        timed_out=True,
    )


def run_owner_command(
    argv: Sequence[str],
    *,
    timeout: float,
    state_root: str | Path,
    documents_root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> CommandResult:
    """Run an owner command in a write-restricted process group, never bare."""
    command = normalize_argv(argv)
    if timeout <= 0:
        raise ValueError("owner command timeout must be positive")
    state, documents = require_disjoint_roots(
        state_root,
        documents_root if documents_root is not None else Path.home() / "Documents",
    )
    state.mkdir(parents=True, exist_ok=True)
    state, documents = require_disjoint_roots(state, documents)
    sandboxed_argv = _sandbox_argv(command, state)
    if sandboxed_argv is None:
        return CommandResult(
            argv=command,
            exit_code=_ISOLATION_UNAVAILABLE_EXIT,
            stdout="",
            stderr="Documents execution isolation unavailable; owner command was not started\n",
            timed_out=False,
        )
    cwd, environment = _execution_environment(state, documents, environ)
    try:
        process = subprocess.Popen(
            sandboxed_argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            cwd=cwd,
            env=environment,
            start_new_session=True,
        )
    except FileNotFoundError:
        return CommandResult(
            argv=command,
            exit_code=127,
            stdout="",
            stderr=f"owner command not found: {command[0]}\n",
            timed_out=False,
        )
    except OSError as exc:
        return CommandResult(
            argv=command,
            exit_code=126,
            stdout="",
            stderr=f"owner command could not run: {exc}\n",
            timed_out=False,
        )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        return _timeout_result(process, command=command, timeout=timeout)
    return CommandResult(
        argv=command,
        exit_code=process.returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=False,
    )
