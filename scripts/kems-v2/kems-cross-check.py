#!/usr/bin/env python3
"""Cross-domain KEMS integrity checker.

The v2.1.1 tool assumed four hard-coded external roots and required symlinked
tool copies.  v2.2.0 removes that accident-prone coupling: callers pass one or
more workspace-owned domain roots, and this checker validates each domain's
ontology and declared counts directly.

Usage:
  python3 kems-cross-check.py --domains /path/a,/path/b
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ONTOLOGY_FILES = (
    "metamodel.yaml",
    "classes.yaml",
    "relations.yaml",
    "layers.yaml",
    "instances.yaml",
    "gaps.yaml",
    "aliases.yaml",
    "associations.yaml",
    "constraints.yaml",
)


def _load_yaml(path: Path) -> tuple[dict, str | None]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        return {}, f"missing file: {path}"
    except yaml.YAMLError as exc:
        return {}, f"invalid YAML in {path}: {exc}"
    if not isinstance(value, dict):
        return {}, f"YAML mapping expected in {path}"
    return value, None


def check_domain(name: str, root: Path) -> tuple[bool, list[str]]:
    """Return (passing, issues); warnings are reported separately from failures."""
    failures: list[str] = []
    warnings: list[str] = []
    if not root.is_dir():
        return False, [f"{name}: domain root does not exist ({root})"]

    ontology = root / "_entities" / "ontology"
    values: dict[str, dict] = {}
    for filename in ONTOLOGY_FILES:
        value, error = _load_yaml(ontology / filename)
        if error:
            failures.append(f"{name}: {error}")
        values[filename] = value

    instances = values["instances.yaml"].get("instances", []) or []
    edges = values["associations.yaml"].get("edges", []) or []
    if values["instances.yaml"].get("total_instances", len(instances)) != len(instances):
        failures.append(f"{name}: instances total does not match instances length")
    if values["associations.yaml"].get("total_edges", len(edges)) != len(edges):
        failures.append(f"{name}: edges total does not match edges length")

    known_classes = {item.get("id") for item in values["classes.yaml"].get("classes", []) or []}
    known_relations = {item.get("id") for item in values["relations.yaml"].get("relations", []) or []}
    known_instances = {item.get("id") for item in instances if item.get("id")}
    for item in instances:
        if item.get("class") not in known_classes:
            failures.append(f"{name}: instance {item.get('id', '?')} references unknown class {item.get('class', '?')}")
    for edge in edges:
        if edge.get("source") not in known_instances:
            failures.append(f"{name}: edge {edge.get('id', '?')} references unknown source {edge.get('source', '?')}")
        if edge.get("target") not in known_instances:
            failures.append(f"{name}: edge {edge.get('id', '?')} references unknown target {edge.get('target', '?')}")
        if edge.get("relation") not in known_relations:
            failures.append(f"{name}: edge {edge.get('id', '?')} references unknown relation {edge.get('relation', '?')}")

    if not list((root / "_entities" / "models").glob("*.md")):
        warnings.append(f"{name}: no M1 models yet")
    if failures:
        return False, failures + [f"{name}: warning {issue}" for issue in warnings]
    return True, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-domain KEMS workspace integrity check")
    parser.add_argument(
        "--domains",
        required=True,
        help="comma-separated workspace-owned domain roots; external defaults are intentionally not provided",
    )
    args = parser.parse_args()

    all_ok = True
    for raw in args.domains.split(","):
        root = Path(raw.strip()).expanduser().resolve()
        ok, issues = check_domain(root.name or str(root), root)
        failures = [issue for issue in issues if not issue.startswith("warning ")]
        warnings = [issue for issue in issues if issue.startswith("warning ")]
        state = "PASS" if not failures else "FAIL"
        print(f"{state} {root.name or root}")
        for issue in failures:
            print(f"  ERROR {issue}")
        for issue in warnings:
            print(f"  WARN  {issue}")
        all_ok = all_ok and ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
