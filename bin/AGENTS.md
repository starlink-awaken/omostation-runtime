<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-08-02 | Updated: 2026-08-02 -->

# bin/

## Purpose
`bin/` is the workspace **operations and scripting hub** — a collection of CLI tools, automation scripts, and governance utilities that operate at the workspace level. It provides the command-line interface for agent workflows, health monitoring, SSOT management, submodule operations, and governance enforcement. This is the primary tooling layer for workspace-level automation and is the entry point for most operational tasks.

## Key Files
| File | Description |
|------|-------------|
| `agent-workflow.py` | Agent workflow lifecycle orchestrator — bootstrap, start, claim, verify, closeout, compliance |
| `compass_radar.py` | Health score computation and governance radar (ISC-3 composite) |
| `commit-assist.py` | Git commit assistant with style detection |
| `layer-dependency-check.py` | Cross-layer dependency validation |
| `ssot-watcher.py` | SSOT file change detection and alerting |
| `check_health_ssot.py` | Health score SSOT consistency checker |
| `classify_planned.py` | Planned task classification (needs-human vs auto-distributable) |
| `cross_package_api_map.py` | Cross-package API surface mapping |
| `migrate-port-env-var.py` | Port and environment variable migration tool |
| `git-health-hook.py` | Git hook health monitoring |
| `submodule-gitlink-check.py` | Submodule gitlink validation |
| `submodule-reachability-gate.py` | Submodule reachability pre-push gate |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `gac/` | Governance toolkit — local gate, worktree guard, KOS sync, evidence gate |
| `ssot/` | SSOT lint, guardian, and doc-ssot validation |
| `adr/` | ADR management utilities |
| `mof/` | MOF protocol tools and agent redlines generator |
| `delivery/` | Delivery pipeline tools including x3-auto-distribute |
| `decks/` | Presentation and reporting tools |
| `collab/` | Collaboration and handoff tools |
| `tests/` | Workspace-level tests for bin/ scripts |

## For AI Agents

### Working In This Directory
- Most scripts use `uv run --with "pyyaml" python` for execution
- `agent-workflow.py` is the primary workflow orchestrator — use `bootstrap` before any editing session
- GaC scripts enforce governance rules — don't bypass them without explicit user approval
- SSOT files (`.omo/state/*.yaml`) should be read through scripts, not hard-coded

### Testing Requirements
```bash
# Run bin/ tests
python -m pytest bin/tests/ -v

# Run specific script tests
uv run --with "pyyaml" python "bin/tests/test_agent_workflow.py" -v
```

### Common Patterns
- Scripts accept `--json` flag for machine-readable output
- Most scripts use `argparse` with subcommands
- Error handling follows: print to stderr, exit non-zero on failure

## Dependencies

### Internal
- `.omo/state/system.yaml` — runtime state (read, don't hard-code)
- `protocols/` — port/vault/x-axis registries
- `projects/omo/` — OMO governance kernel

### External
- Python 3.13+
- `pyyaml` — YAML parsing
- `pytest` — test framework

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
