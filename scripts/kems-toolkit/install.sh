#!/bin/bash
# KEMS installer — `kems` CLI + `kems-mcp` MCP → ~/.local/bin
set -e

KEMS_HOME="${KEMS_HOME:-$HOME/Documents/学习进化/体系/KEMS}"
BIN_DIR="$HOME/.local/bin"

if [ ! -f "$KEMS_HOME/.kems/_scripts/kems-cli.py" ]; then
    echo "KEMS not found at $KEMS_HOME — set KEMS_HOME or clone first."
    exit 1
fi

mkdir -p "$BIN_DIR"

cat > "$BIN_DIR/kems" << 'W'
#!/usr/bin/env bash
KEMS_HOME="${KEMS_HOME:-$HOME/Documents/学习进化/体系/KEMS}"
exec python3 "$KEMS_HOME/.kems/_scripts/kems-cli.py" "$@"
W
chmod +x "$BIN_DIR/kems"

cat > "$BIN_DIR/kems-mcp" << 'W'
#!/usr/bin/env bash
KEMS_HOME="${KEMS_HOME:-$HOME/Documents/学习进化/体系/KEMS}"
exec python3 "$KEMS_HOME/.kems/_scripts/kems-mcp.py" "$@"
W
chmod +x "$BIN_DIR/kems-mcp"

SHELL_RC=""
case "$SHELL" in */zsh) SHELL_RC="$HOME/.zshrc";; */bash) SHELL_RC="$HOME/.bashrc";; *) SHELL_RC="$HOME/.zshrc";; esac

if ! echo "$PATH" | grep -q "$BIN_DIR"; then
    echo "export PATH=\"$BIN_DIR:\$PATH\"" >> "$SHELL_RC"
fi

echo ""
echo "KEMS installed"
echo "  CLI:  kems init my-project"
echo "  MCP:  kems-mcp"
echo ""
echo "  MCP config (add to Cowork settings):"
echo "  { \"mcpServers\": { \"kems\": { \"command\": \"$BIN_DIR/kems-mcp\" } } }"
echo ""
echo "  source $SHELL_RC"
