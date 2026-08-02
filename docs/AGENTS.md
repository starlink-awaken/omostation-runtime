<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-08-02 | Updated: 2026-08-02 -->

# docs/

## Purpose
`docs/` is the **documentation center** for the omostation workspace. It contains architecture documentation, governance closeout reports, ISA specifications, operations runbooks, ADR records, and machine-generated documentation snapshots. This is the authoritative source for system design decisions, engineering processes, and governance audit trails.

## Key Files
| File | Description |
|------|-------------|
| `ARCHITECTURE-DETAILED-MAP.md` | Detailed architecture map — component relationships and data flow |
| `FUNCTIONAL-CAPABILITY-MAP.md` | Functional capability inventory |
| `I0-AGORA-CALLCHAIN.md` | Agora MCP Hub call chain documentation |
| `AGENT-ISOLATION-ROLLOUT.md` | Agent isolation rollout plan and status |
| `VISION-ROADMAP.md` (generated) | Vision and roadmap snapshot |
| `PANORAMA.md` (generated) | System panorama snapshot |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `generated/` | Machine-generated docs — indexes, snapshots, reports (gitignored) |
| `architecture/` | Architecture deep-dive documents |
| `closeout/` | Phase closeout reports |
| `contracts/` | Interface and integration contracts |
| `isa/` | ISA (Interface Specification Agreement) documents |
| `operations/` | Operations runbooks and workflow guides |
| `proposals/` | Design proposals and RFCs |
| `reports/` | Audit and health reports |
| `local-compute/` | Local compute architecture docs |
| `overview/` | System overview documents |

## For AI Agents

### Working In This Directory
- \`generated/\` is gitignored — machine outputs, don't manually edit
- Architecture docs should reference \`ARCHITECTURE.md\` (root) for stable contracts
- Closeout reports follow the template in \`AGENTS.md §9\`
- Use \`make ssot-status\` to check for documentation drift

### Testing Requirements
```bash
# Documentation SSOT lint
uv run --with "pyyaml" python "bin/ssot/doc-ssot-lint.py" --json
```

### Common Patterns
- Auto-generated files have \`<!-- GENERATED -->\` header marker
- Manual annotations go below \`<!-- MANUAL -->\` separator
- File naming: \`YYYY-MM-DD-topic.md\` for dated docs

## Dependencies

### Internal
- \`ARCHITECTURE.md\` (root) — stable architecture contracts
- \`.omo/_knowledge/\` — decision records and patterns
- \`bin/ssot/\` — documentation SSOT linting tools

### External
- None direct

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
