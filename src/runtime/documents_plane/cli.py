"""Thin `runtime documents` CLI router; all other commands remain legacy-owned."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence

from .jobs import JobRegistry, run_job
from .paths import documents_content_root, runtime_state_root

DEFAULT_REGISTRY = JobRegistry()


def _documents_main(
    argv: Sequence[str], *, registry: JobRegistry, environ: Mapping[str, str]
) -> int:
    parser = argparse.ArgumentParser(prog="runtime documents")
    subparsers = parser.add_subparsers(dest="documents_command", required=True)
    run_parser = subparsers.add_parser(
        "run", help="Run an explicitly registered owner job"
    )
    run_parser.add_argument("job_id")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)

    if (
        args.documents_command != "run"
    ):  # pragma: no cover - argparse owns this boundary
        return 2
    try:
        result = run_job(
            registry,
            args.job_id,
            dry_run=args.dry_run,
            documents_root=documents_content_root(environ),
            state_root=runtime_state_root(environ),
        )
    except ValueError as exc:
        if args.json_output:
            print(
                json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False)
            )
        else:
            print(f"runtime documents: {exc}", file=sys.stderr)
        return 2

    if args.json_output:
        print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    else:
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        print(f"{result.job_id}: {result.status}")
    return result.exit_code


def main(
    argv: Sequence[str] | None = None,
    *,
    registry: JobRegistry | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Route only `documents`; delegate every other argument vector unchanged."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] != "documents":
        from runtime.cli import main as legacy_main

        return legacy_main(arguments)
    return _documents_main(
        arguments[1:],
        registry=DEFAULT_REGISTRY if registry is None else registry,
        environ=os.environ if environ is None else environ,
    )
