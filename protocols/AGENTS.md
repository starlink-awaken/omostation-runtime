<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-08-02 | Updated: 2026-08-02 -->

# protocols/

## Purpose
`protocols/` is the **SSOT contract registry** for cross-cutting infrastructure concerns. It defines and registers port assignments, vault paths, X-axis governance rules, and protocol-level constraints. All projects read from these registries rather than hard-coding values — ensuring consistency and enabling centralized governance.

## Key Files
| File | Description |
|------|-------------|
| `port-registry.yaml` | Port assignment registry — all service ports registered here |
| `vault-paths.yaml` | Vault path definitions — centralized path configuration |
| `*-registry.yaml` | Various protocol/type registries (MOF types, BOS services, etc.) |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| *(flat structure — no subdirectories)* | |

## For AI Agents

### Working In This Directory
- **Read-only for agents.** Register changes through the \`omo\` CLI or MCP, not direct file I/O
- Port assignments: read from \`port-registry.yaml\`, never hard-code port numbers
- Vault paths: read from \`vault-paths.yaml\`, don't construct paths manually
- After modifying any registry, run \`make ssot-sync\` to propagate changes

### Testing Requirements
```bash
# Port hardcode detection
python -m pytest tests/test_hardcoded_ports.py -v

# Registry sync validation
python -m pytest tests/test_registry_sync.py -v
```

### Common Patterns
- Registries use YAML with \`metadata\` (created_at, source) and \`entries\` arrays
- Each entry has: \`id\`, \`name\`, \`description\`, \`owner\`, \`status\`
- Deprecation: mark \`status: deprecated\`, don't remove entries

## Dependencies

### Internal
- \`projects/omo/\` — OMO governance kernel manages registry consistency
- \`projects/ecos/\` — ECOS L0 constraint definitions
- \`bin/ssot/\` — SSOT lint and guardian tools

### External
- None direct

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
