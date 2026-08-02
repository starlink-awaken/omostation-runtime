<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-08-02 | Updated: 2026-08-02 -->

# data/

## Purpose
`data/` is the **runtime data substrate** for the omostation workspace. It stores persistent runtime artifacts including the KOS (Knowledge Operating System) SQLite index, GBrain graph database, vector embeddings index, cockpit cards data, and access policy configurations. This directory is the durable state layer that powers knowledge search, graph queries, and runtime governance.

## Key Files
| File | Description |
|------|-------------|
| `gbrain_graph.sqlite` | GBrain knowledge graph — entity/relationship storage for semantic queries |
| `vector_index.sqlite` | Vector embeddings index for semantic similarity search |
| `kos/` | KOS knowledge index directory (SQLite + manifest) |
| `runtime-space-access-policy.yaml` | Access control policy for runtime data space |
| `system-data-access-policy.yaml` | System-level data access policy |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `kos/` | Knowledge Operating System — SQLite full-text/semantic search index |
| `cards/` | Cockpit task cards and governance data |
| `驾驶舱/` | Cockpit runtime data (Chinese-named legacy directory) |
| `_index/` | Data indexing metadata and manifests |

## For AI Agents

### Working In This Directory
- **SQLite files are managed by daemons.** Do not write to them directly.
- KOS queries go through \`mcp-server-kos\` MCP tools, not direct SQL
- GBrain graph is accessed through \`gbrain/\` project tools, not raw SQLite
- Access policy YAML files define who/what can read or write data

### Testing Requirements
```bash
# KOS-specific tests
uv run --with "pyyaml" python "bin/ssot/test-mcp-kos.py"
```

### Common Patterns
- SQLite databases follow: read-only access for agents, daemon-managed writes
- Access policies use \`allowed_roles\`, \`denied_paths\`, \`max_query_depth\`

## Dependencies

### Internal
- \`projects/kairon/\` — KOS daemon that manages the knowledge index
- \`projects/gbrain/\` — GBrain daemon that manages the graph DB
- \`bin/gac/gac-kos-sync.py\` — KOS-governance synchronization

### External
- SQLite 3 — embedded database
- \`mcp-server-kos\` — MCP protocol server for knowledge queries

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
