"""Thin `runtime documents` CLI router; all other commands remain legacy-owned."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from .jobs import JobRegistry, JobSpec, run_job
from .paths import (
    DocumentsPlanePathError,
    documents_content_root,
    resolve_documents_read_path,
    runtime_state_root,
)


def _default_registry(environ: Mapping[str, str]) -> JobRegistry:
    """Build the small, explicit owner set shipped with Runtime.

    Owner commands stay outside Documents.  Each job declares its Documents
    read scope; Runtime state remains the only write root.
    """
    documents_root = documents_content_root(environ)
    registry_path = environ.get(
        "L4_DOMAIN_REGISTRY",
        str(documents_root / "@公共" / "_control" / "L4-DOMAIN-REGISTRY.yaml"),
    )
    try:
        registry_relative_path = (
            Path(registry_path).expanduser().resolve().relative_to(documents_root)
        )
        registry_path = str(
            resolve_documents_read_path(documents_root, registry_relative_path)
        )
    except ValueError as exc:
        raise DocumentsPlanePathError(
            "L4_DOMAIN_REGISTRY must be inside DOCUMENTS_CONTENT_ROOT"
        ) from exc
    l4_command = environ.get("L4_KERNEL_COMMAND", "l4-kernel")
    registry = JobRegistry()
    registry.register(
        JobSpec(
            job_id="l4-registry-list",
            reads=(str(registry_relative_path),),
            writes=(),
            owner="l4-kernel",
            schedule="manual",
            timeout=30,
            evidence_path="l4-registry-list.json",
            fail_closed=True,
        ),
        [l4_command, "registry", "list", "--registry", registry_path, "--json"],
    )
    registry.register(
        JobSpec(
            job_id="l4-content-audit",
            reads=(".",),
            writes=(),
            owner="l4-kernel",
            schedule="manual",
            timeout=300,
            evidence_path="l4-content-audit.json",
            fail_closed=True,
        ),
        [l4_command, "content", "audit", str(documents_root), "--json"],
    )
    registry.register(
        JobSpec(
            job_id="documents-weijian-facts-audit",
            reads=("@工作文档/卫健委/_entities/facts",),
            writes=(),
            owner="runtime-facts",
            schedule="manual",
            timeout=60,
            evidence_path="documents-weijian-facts-audit.json",
            fail_closed=True,
            evidence_projection="facts-audit-v1",
        ),
        [
            sys.executable,
            "-m",
            "runtime.documents_plane.facts",
            "audit",
            "--domain-relative",
            "@工作文档/卫健委",
        ],
    )
    registry.register(
        JobSpec(
            job_id="documents-weijian-kems-check",
            reads=("@工作文档/卫健委", "_inbox"),
            writes=("kems",),
            owner="runtime-kems",
            schedule="manual",
            timeout=60,
            evidence_path="documents-weijian-kems-check.json",
            fail_closed=True,
            evidence_projection="kems-check-v1",
        ),
        [
            sys.executable,
            "-m",
            "runtime.documents_plane.kems",
            "check",
            "--domain-relative",
            "@工作文档/卫健委",
            "--extra-inbox-relative",
            "_inbox",
            "--state-relative",
            "kems/weijian-check.json",
        ],
    )
    return registry


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
    environment = os.environ if environ is None else environ
    try:
        selected_registry = (
            _default_registry(environment) if registry is None else registry
        )
    except DocumentsPlanePathError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 2
    return _documents_main(
        arguments[1:], registry=selected_registry, environ=environment
    )
