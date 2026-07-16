#!/usr/bin/env bash
# OPC (One-Person Company) — One-line installer
# Usage: curl -sSL https://raw.githubusercontent.com/.../install.sh | bash
#   or:  bash install.sh [--no-claude] [--no-init]

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${BLUE}[opc]${NC} $*"; }
ok()   { echo -e "${GREEN}  ✓${NC} $*"; }
warn() { echo -e "${YELLOW}  ⚠${NC} $*"; }
fail() { echo -e "${RED}  ✗${NC} $*"; }

SKIP_CLAUDE=false
SKIP_INIT=false
for arg in "$@"; do
    case "$arg" in
        --no-claude) SKIP_CLAUDE=true ;;
        --no-init)   SKIP_INIT=true ;;
        --help|-h)
            echo "Usage: install.sh [--no-claude] [--no-init]"
            echo "  --no-claude  Skip Claude Code CLI installation"
            echo "  --no-init    Skip opc init"
            exit 0
            ;;
    esac
done

# ── 1. Check Python ──
log "Checking Python..."
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0")
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fail "Python >= 3.10 is required but not found."
    echo "  Install Python: https://www.python.org/downloads/"
    exit 1
fi
ok "Python found: $PYTHON ($($PYTHON --version 2>&1))"

# ── 2. Check pip ──
log "Checking pip..."
if ! $PYTHON -m pip --version &>/dev/null; then
    fail "pip not found. Installing..."
    $PYTHON -m ensurepip --upgrade 2>/dev/null || {
        fail "Cannot install pip. Please install it manually."
        exit 1
    }
fi
ok "pip available"

# ── 3. Install OPC ──
log "Installing OPC..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$REPO_DIR/pyproject.toml" ]; then
    # Uninstall existing version first to avoid conflicts
    $PYTHON -m pip uninstall opc -y 2>/dev/null || true
    # Installing from local repo
    $PYTHON -m pip install -e "$REPO_DIR" 2>&1 | tail -5
    if [ $? -ne 0 ]; then
        fail "Installation failed. Try manually: pip install -e $REPO_DIR"
        exit 1
    fi
    ok "OPC installed from local source"
else
    # Installing from PyPI (if published)
    $PYTHON -m pip uninstall opc -y 2>/dev/null || true
    $PYTHON -m pip install opc 2>&1 | tail -5 || {
        fail "Cannot install OPC. Run this script from the repo directory, or publish to PyPI."
        exit 1
    }
    ok "OPC installed from PyPI"
fi

# ── 4. Check/Install Claude Code CLI ──
if [ "$SKIP_CLAUDE" = false ]; then
    log "Checking Claude Code CLI..."
    if command -v claude &>/dev/null; then
        VERSION=$(claude --version 2>/dev/null | head -1 || echo "unknown")
        ok "Claude Code CLI found: $VERSION"
    else
        warn "Claude Code CLI not found"
        if command -v npm &>/dev/null; then
            read -rp "  Install Claude Code CLI via npm? [Y/n] " answer
            answer=${answer:-Y}
            if [[ "$answer" =~ ^[Yy] ]]; then
                log "  Installing @anthropic-ai/claude-code..."
                npm install -g @anthropic-ai/claude-code 2>&1 | tail -3
                if command -v claude &>/dev/null; then
                    ok "Claude Code CLI installed"
                else
                    warn "Installation may have succeeded. Try: claude --version"
                fi
            else
                warn "Skipped. Install later: npm install -g @anthropic-ai/claude-code"
            fi
        else
            warn "npm not found. Please install Node.js first: https://nodejs.org/"
            warn "Then run: npm install -g @anthropic-ai/claude-code"
        fi
    fi
else
    log "Claude CLI check skipped"
fi

# ── 5. Initialize OPC ──
if [ "$SKIP_INIT" = false ]; then
    log "Initializing OPC..."
    opc init --yes 2>&1 | tail -5
    ok "OPC initialized"
else
    log "OPC init skipped"
fi

# ── Done ──
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  OPC installed successfully!${NC}"
echo ""
echo "  Next steps:"
echo "    1. Configure API key:  opc setup"
echo "    2. Launch UI:          opc ui"
echo "    3. Open browser:       http://localhost:8765"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
