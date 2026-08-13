"""Thin `runtime documents` CLI router; all other commands remain legacy-owned."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml

from .jobs import JobRegistry, JobSpec, run_job
from .paths import (
    DocumentsPlanePathError,
    documents_content_root,
    resolve_documents_read_path,
    runtime_state_root,
)

_CONTROLLER_SHADOW_ACTION = "shadow_legacy_controller"
_CONTROLLER_SHADOW_SCHEMA = "runtime.documents-controller-shadow.evidence.v2"
_CONTROLLER_SHADOW_READS = (
    "@工作文档/卫健委/_control",
    "@工作文档/卫健委/_entities",
    "@工作文档/卫健委/_meta",
    "@工作文档/卫健委/_runtime",
    "@工作文档/卫健委/_storage",
    "@工作文档/卫健委/_knowledge",
)
_CONTROLLER_SHADOW_EVIDENCE = (
    "control/evidence/documents-weijian-controller-shadow/"
    "documents-weijian-controller-shadow.json"
)
_CONTROLLER_SHADOW_EVIDENCE_PREFIX = (
    "control/evidence/documents-weijian-controller-shadow/"
)


def _workspace_binding_registry_path(environ: Mapping[str, str]) -> Path:
    configured = environ.get("DOCUMENTS_DOMAIN_PROJECTS_REGISTRY")
    if configured:
        return Path(configured).expanduser()
    workspace_root = environ.get("WORKSPACE_ROOT")
    if workspace_root:
        return (
            Path(workspace_root).expanduser()
            / ".omo"
            / "_truth"
            / "registry"
            / "documents-domain-projects.yaml"
        )
    raise DocumentsPlanePathError(
        "DOCUMENTS_DOMAIN_PROJECTS_REGISTRY or WORKSPACE_ROOT is required for Workspace-owned Documents jobs"
    )


def _controller_shadow_job_spec(environ: Mapping[str, str]) -> JobSpec:
    """Load the one controller-shadow declaration from the Workspace binding SSOT."""

    path = _workspace_binding_registry_path(environ)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise DocumentsPlanePathError(
            "Workspace Documents binding registry is unavailable"
        ) from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("runtime_jobs"), list):
        raise DocumentsPlanePathError(
            "Workspace Documents binding registry has invalid runtime_jobs"
        )
    matches = [
        item
        for item in raw["runtime_jobs"]
        if isinstance(item, dict)
        and item.get("id") == "documents-weijian-controller-shadow"
        and item.get("action") == _CONTROLLER_SHADOW_ACTION
    ]
    if len(matches) != 1:
        raise DocumentsPlanePathError(
            "Workspace controller shadow job must be declared exactly once"
        )
    job = matches[0]
    reads = job.get("reads")
    timeout = job.get("timeout_seconds")
    if (
        job.get("domain_id") != "work-weijian"
        or job.get("owner") != "runtime-control"
        or job.get("schedule") != "manual"
        or job.get("writes") != []
        or job.get("fail_closed") is not True
        or job.get("evidence_schema") != _CONTROLLER_SHADOW_SCHEMA
        or reads != list(_CONTROLLER_SHADOW_READS)
        or job.get("evidence_relative_path") != _CONTROLLER_SHADOW_EVIDENCE
        or isinstance(timeout, bool)
        or not isinstance(timeout, int)
        or timeout <= 0
    ):
        raise DocumentsPlanePathError(
            "Workspace controller shadow job has an invalid contract"
        )
    return JobSpec(
        job_id="documents-weijian-controller-shadow",
        reads=tuple(reads),
        writes=(),
        owner="runtime-control",
        schedule="manual",
        timeout=timeout,
        evidence_path=_CONTROLLER_SHADOW_EVIDENCE.removeprefix(
            _CONTROLLER_SHADOW_EVIDENCE_PREFIX
        ),
        fail_closed=True,
        evidence_projection="controller-shadow-v2",
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
    registry.register(
        JobSpec(
            job_id="documents-weijian-control-health",
            reads=(
                "@工作文档/卫健委/_control/signals.md",
                "@工作文档/卫健委/_entities/facts.md",
            ),
            writes=(),
            owner="runtime-control",
            schedule="manual",
            timeout=30,
            evidence_path="documents-weijian-control-health.json",
            fail_closed=True,
            evidence_projection="control-health-v1",
        ),
        [
            sys.executable,
            "-m",
            "runtime.documents_plane.control_health",
            "inspect",
            "--domain-relative",
            "@工作文档/卫健委",
        ],
    )
    if environ.get("DOCUMENTS_DOMAIN_PROJECTS_REGISTRY") or environ.get(
        "WORKSPACE_ROOT"
    ):
        registry.register(
            _controller_shadow_job_spec(environ),
            [
                sys.executable,
                "-m",
                "runtime.documents_plane.controller_shadow",
                "inspect",
                "--domain-relative",
                "@工作文档/卫健委",
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
