---
type: ssot
owner: governance-team
last_updated: 2026-09-03
---

# runtime API / Usage Reference

> Quick reference for using **runtime** programmatically and from the command line.

## Command Line

- `uv run python -m runtime` — CLI
- `runtime documents run documents-learning-decay --json` — read-only concept
  lifecycle scan; aggregate evidence is stored under Runtime state.
- `runtime documents run documents-learning-orphans --json` — read-only orphan
  concept summary; it never prints concept names or source text.
- `make fmt` — format
- `make sync-state` — sync state

### Learning concept owner jobs

The two learning jobs read only the Documents content path declared by the
Workspace binding registry:
`@学习进化/_knowledge/50-concepts`. They are explicit manual Runtime jobs,
fail closed on binding/path errors, declare `writes: []`, and publish a
`runtime.documents-learning-decay.v1` aggregate receipt below
`OMOSTATION_RUNTIME_STATE_ROOT`. `attention` is a truthful result when the
corpus contains orphan or stale/decayed concepts; it is not an execution
failure. The legacy `mark-stale` writer is intentionally not routed here until
its Documents-write contract receives a separate governed owner.

## Programmatic API

Import `runtime.matrix`, `runtime.scheduler`, or `runtime.kei`.

## Configuration

- Stack: python
- Dependencies: see [`../pyproject.toml`](../pyproject.toml) (Python) or [`../package.json`](../package.json) (TypeScript).
- Environment variables and ports: see workspace `protocols/port-registry.yaml` and root `.env.example`.

## Tests

See [`../README.md`](../README.md) for the test command.
