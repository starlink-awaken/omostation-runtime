"""Narrow subprocess adapter for explicitly registered Documents jobs."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass


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


def run_owner_command(argv: Sequence[str], *, timeout: float) -> CommandResult:
    """Run one owner command with no shell and a bounded execution time."""
    command = normalize_argv(argv)
    if timeout <= 0:
        raise ValueError("owner command timeout must be positive")
    try:
        completed = subprocess.run(
            command,
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stderr = _text(exc.stderr)
        if stderr and not stderr.endswith("\n"):
            stderr += "\n"
        return CommandResult(
            argv=command,
            exit_code=124,
            stdout=_text(exc.stdout),
            stderr=f"{stderr}owner command timed out after {timeout:g}s\n",
            timed_out=True,
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
    return CommandResult(
        argv=command,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        timed_out=False,
    )
