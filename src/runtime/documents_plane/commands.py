"""Isolated subprocess adapter for explicitly registered Documents jobs."""

from __future__ import annotations

import os
import secrets
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .paths import require_disjoint_roots

_ISOLATION_UNAVAILABLE_EXIT = 125
_REAP_GRACE_SECONDS = 0.25
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


@dataclass(frozen=True)
class CommandResult:
    """Stable process outcome returned to the Runtime adapter."""

    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    setup_error: str | None = None


def normalize_argv(argv: Sequence[str]) -> tuple[str, ...]:
    """Accept only a non-empty argv list; shell strings are intentionally refused."""
    if isinstance(argv, str) or not argv or not all(isinstance(value, str) and value for value in argv):
        raise ValueError("owner command must be a non-empty argv list of strings")
    return tuple(argv)


def _decode(value: bytes | None) -> str:
    return (value or b"").decode("utf-8", errors="replace")


def _sbpl_quote(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


def _sandbox_argv(command: tuple[str, ...], allowed_write_roots: Sequence[Path]) -> tuple[str, ...] | None:
    """Build a macOS-only no-shell argv; other platforms must fail closed."""
    sandbox_exec = "/usr/bin/sandbox-exec"
    if sys.platform != "darwin" or not os.path.isfile(sandbox_exec):
        return None
    profile_rules = ["(version 1)", "(allow default)", "(deny file-write*)"]
    profile_rules.extend(f'(allow file-write* (subpath "{_sbpl_quote(root)}"))' for root in allowed_write_roots)
    return (sandbox_exec, "-p", "\n".join(profile_rules), *command)


def _execution_environment(
    work_root: Path,
    output_root: Path,
    documents_root: Path,
    environ: Mapping[str, str] | None,
) -> tuple[Path, dict[str, str]]:
    """Keep conventional owner writes inside a fresh, private run work root."""
    runtime_root = work_root
    directories = {
        "home": runtime_root / "home",
        "work": runtime_root / "work",
        "tmp": runtime_root / "tmp",
        "cache": runtime_root / "xdg" / "cache",
        "config": runtime_root / "xdg" / "config",
        "xdg_state": runtime_root / "xdg" / "state",
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
            "OMOSTATION_RUNTIME_STATE_ROOT": str(output_root),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return directories["work"], environment


def _open_directory_nofollow(path: Path) -> int:
    """Open every component without following an owner-controlled symlink."""
    absolute = Path(os.path.abspath(path))
    current_fd = os.open(absolute.anchor, _DIR_FLAGS)
    try:
        for part in absolute.parts[1:]:
            child_fd = os.open(part, _DIR_FLAGS, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = child_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _create_fresh_work_root(output_root: Path, work_root: str | Path | None) -> Path:
    """Create one unpredictable run directory below an anchored no-follow parent."""
    if work_root is None:
        parent_path = output_root / ".runtime-runs"
        output_fd = _open_directory_nofollow(output_root)
        try:
            try:
                os.mkdir(parent_path.name, 0o700, dir_fd=output_fd)
            except FileExistsError:
                pass
            parent_fd = os.open(parent_path.name, _DIR_FLAGS, dir_fd=output_fd)
        finally:
            os.close(output_fd)
    else:
        parent_path = Path(os.path.abspath(Path(work_root).expanduser()))
        parent_fd = _open_directory_nofollow(parent_path)
    try:
        for _ in range(16):
            name = secrets.token_hex(16)
            try:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                continue
            fresh_fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
            os.close(fresh_fd)
            return parent_path / name
    finally:
        os.close(parent_fd)
    raise OSError("could not allocate a unique owner work root")


def _terminate_direct_children(parent_pid: int) -> None:
    """Best-effort cleanup for children that may have escaped the process group."""
    try:
        listed = subprocess.run(
            ["/usr/bin/pgrep", "-P", str(parent_pid)],
            check=False,
            capture_output=True,
            timeout=_REAP_GRACE_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    for token in listed.stdout.split():
        try:
            os.kill(int(token), signal.SIGKILL)
        except (ProcessLookupError, ValueError, OSError):
            pass


def _timeout_result(process: subprocess.Popen[bytes], *, command: tuple[str, ...], timeout: float) -> CommandResult:
    """Bounded kill/reap path; detached pipe holders cannot stall Runtime forever."""
    _terminate_direct_children(process.pid)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        try:
            process.kill()
        except OSError:
            pass
    try:
        stdout, stderr = process.communicate(timeout=_REAP_GRACE_SECONDS)
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = exc.output, exc.stderr
        for pipe in (process.stdout, process.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:
                    pass
    except OSError:
        stdout, stderr = b"", b""
    stderr_text = _decode(stderr)
    if stderr_text and not stderr_text.endswith("\n"):
        stderr_text += "\n"
    return CommandResult(
        argv=command,
        exit_code=124,
        stdout=_decode(stdout),
        stderr=f"{stderr_text}owner command timed out after {timeout:g}s\n",
        timed_out=True,
    )


def run_owner_command(
    argv: Sequence[str],
    *,
    timeout: float,
    state_root: str | Path,
    documents_root: str | Path | None = None,
    allowed_write_roots: Sequence[str | Path] | None = None,
    work_root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> CommandResult:
    """Run an owner in its private output subtree, never as a bare process."""
    command = normalize_argv(argv)
    if timeout <= 0:
        raise ValueError("owner command timeout must be positive")
    output_root, documents = require_disjoint_roots(
        state_root,
        documents_root if documents_root is not None else Path.home() / "Documents",
    )
    try:
        output_root.mkdir(parents=True, exist_ok=True)
        output_root, documents = require_disjoint_roots(output_root, documents)
        fresh_work = _create_fresh_work_root(output_root, work_root)
        cwd, environment = _execution_environment(fresh_work, output_root, documents, environ)
    except OSError as exc:
        return CommandResult(
            argv=command,
            exit_code=74,
            stdout="",
            stderr=f"owner state setup failed: {exc}\n",
            timed_out=False,
            setup_error=str(exc),
        )
    roots = (
        [output_root]
        if allowed_write_roots is None
        else [Path(root).expanduser().resolve() for root in allowed_write_roots]
    )
    if any(not root.is_relative_to(output_root) for root in roots):
        raise ValueError("owner write permission escapes its output root")
    sandboxed_argv = _sandbox_argv(command, (*roots, fresh_work))
    if sandboxed_argv is None:
        return CommandResult(
            argv=command,
            exit_code=_ISOLATION_UNAVAILABLE_EXIT,
            stdout="",
            stderr="Documents execution isolation unavailable; owner command was not started\n",
            timed_out=False,
        )
    try:
        process = subprocess.Popen(
            sandboxed_argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            shell=False,
            cwd=cwd,
            env=environment,
            start_new_session=True,
        )
    except FileNotFoundError:
        return CommandResult(command, 127, "", f"owner command not found: {command[0]}\n", False)
    except OSError as exc:
        return CommandResult(command, 74, "", f"owner process setup failed: {exc}\n", False, str(exc))
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        return _timeout_result(process, command=command, timeout=timeout)
    return CommandResult(
        argv=command,
        exit_code=process.returncode,
        stdout=_decode(stdout),
        stderr=_decode(stderr),
        timed_out=False,
    )
