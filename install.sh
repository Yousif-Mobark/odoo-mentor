#!/usr/bin/env bash
# Universal installer for the odoo-rpc skill.
#
# Canonical source lives at /opt/odoo-rpc/. This script:
#   1. Symlinks /opt/odoo_rpc.py -> /opt/odoo-rpc/bin/odoo_rpc.py
#   2. Wires the skill into every detected AI assistant on this box.
#   3. (Optional) installs Playwright + Chromium into ~/.odoo_rpc/venv.
#
# Usage:
#   bash /opt/odoo-rpc/install.sh                  # detect & install everywhere
#   bash /opt/odoo-rpc/install.sh --platform claude-code,cursor
#   bash /opt/odoo-rpc/install.sh --no-playwright
#   bash /opt/odoo-rpc/install.sh --uninstall
#
# Safe to re-run — idempotent symlinks.

set -euo pipefail

SRC="/opt/odoo-rpc"
PLATFORMS=""
INSTALL_PW=1
UNINSTALL=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --platform) PLATFORMS="$2"; shift 2 ;;
        --no-playwright) INSTALL_PW=0; shift ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help)
            sed -n '2,20p' "$0" | sed 's/^# \?//'
            exit 0 ;;
        *) echo "Unknown: $1" >&2; exit 2 ;;
    esac
done

log() { printf '==> %s\n' "$*"; }
warn() { printf '!! %s\n' "$*" >&2; }

# ---------- 0. source present? ----------
if [[ ! -f "$SRC/SKILL.md" || ! -f "$SRC/bin/odoo_rpc.py" ]]; then
    warn "$SRC not populated. Expected $SRC/SKILL.md and $SRC/bin/odoo_rpc.py."
    exit 1
fi

# ---------- 1. /opt/odoo_rpc.py symlink ----------
if [[ $UNINSTALL -eq 1 ]]; then
    [[ -L /opt/odoo_rpc.py ]] && rm /opt/odoo_rpc.py && log "removed symlink /opt/odoo_rpc.py"
else
    if [[ -e /opt/odoo_rpc.py && ! -L /opt/odoo_rpc.py ]]; then
        warn "/opt/odoo_rpc.py exists and is not a symlink; backing up"
        mv /opt/odoo_rpc.py "/opt/odoo_rpc.py.bak.$(date +%s)"
    fi
    ln -sfn "$SRC/bin/odoo_rpc.py" /opt/odoo_rpc.py
    chmod +x "$SRC/bin/odoo_rpc.py"
    log "linked /opt/odoo_rpc.py -> $SRC/bin/odoo_rpc.py"
fi

# ---------- 2. platform wiring ----------
# Each platform block is self-contained. Set up on install, remove on uninstall.

wire_claude_code() {
    local dest="$HOME/.claude/skills/odoo-rpc"
    if [[ $UNINSTALL -eq 1 ]]; then
        [[ -L "$dest" ]] && { rm "$dest"; log "claude-code: removed $dest"; }
        [[ -d "$dest" && ! -L "$dest" ]] && warn "claude-code: $dest is a real dir, not touching"
        return
    fi
    mkdir -p "$(dirname "$dest")"
    if [[ -e "$dest" && ! -L "$dest" ]]; then
        warn "claude-code: $dest exists as real dir, replacing with symlink after backup"
        mv "$dest" "${dest}.bak.$(date +%s)"
    fi
    ln -sfn "$SRC" "$dest"
    log "claude-code: linked $dest -> $SRC"
}

wire_opencode() {
    # OpenCode (sst/opencode) looks for commands in ~/.config/opencode/command and
    # agents/skills in ~/.config/opencode/agent. We expose a slash command.
    local dir="$HOME/.config/opencode/command"
    local cmd="$dir/odoo-rpc.md"
    if [[ $UNINSTALL -eq 1 ]]; then
        [[ -L "$cmd" || -f "$cmd" ]] && { rm "$cmd"; log "opencode: removed $cmd"; }
        return
    fi
    mkdir -p "$dir"
    cat > "$cmd" <<EOF
---
description: Investigate and automate a live Odoo instance (v13+). See $SRC/SKILL.md
---

Read the skill at $SRC/SKILL.md and act on it for this request:

!\$ARGUMENTS
EOF
    log "opencode: wrote $cmd"
}

wire_cursor() {
    local dest="$HOME/.cursor/rules/odoo-rpc.mdc"
    if [[ $UNINSTALL -eq 1 ]]; then
        [[ -f "$dest" || -L "$dest" ]] && { rm "$dest"; log "cursor: removed $dest"; }
        return
    fi
    mkdir -p "$(dirname "$dest")"
    cat > "$dest" <<EOF
---
description: Investigate and automate a live Odoo instance (v13+). Load when the user asks about Odoo, prod, staging, xmlrpc, trace a record, ui test odoo, press a button, upgrade a module, etc.
globs: []
alwaysApply: false
---

The user has the odoo-rpc skill at \`$SRC\`. When this rule triggers:

1. Read \`$SRC/SKILL.md\` for the prime directive and command map.
2. Load \`$SRC/references/*.md\` on demand per that file's table.
3. The CLI is at \`/opt/odoo_rpc.py\`. Playwright harness at \`$SRC/scripts/odoo_playwright.py\`.
4. Run \`/opt/odoo_rpc.py doctor\` first in any new session to detect missing config/playwright, and ask the user before proceeding.
EOF
    log "cursor: wrote $dest"
}

wire_copilot() {
    # VS Code / GitHub Copilot: user-level custom instructions file.
    local dir="$HOME/.config/github-copilot"
    local f="$dir/custom-instructions.md"
    local marker_begin="<!-- odoo-rpc:begin -->"
    local marker_end="<!-- odoo-rpc:end -->"
    if [[ $UNINSTALL -eq 1 ]]; then
        [[ -f "$f" ]] || return
        # Strip our block
        python3 - "$f" "$marker_begin" "$marker_end" <<'PY'
import sys, pathlib
p, b, e = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
s = p.read_text()
if b in s and e in s:
    s = s.split(b)[0] + s.split(e,1)[1]
    p.write_text(s.strip() + "\n" if s.strip() else "")
PY
        log "copilot: stripped block from $f"
        return
    fi
    mkdir -p "$dir"
    touch "$f"
    if ! grep -q "$marker_begin" "$f" 2>/dev/null; then
        cat >> "$f" <<EOF

$marker_begin
# odoo-rpc skill

When the user asks about a live Odoo instance (prod, staging, xmlrpc, trace a record,
ui test, press a button, upgrade a module, inspect a view), read the skill at
\`$SRC/SKILL.md\` and follow its prime directive. The CLI is at \`/opt/odoo_rpc.py\`.
Run \`/opt/odoo_rpc.py doctor\` first to detect missing config / Playwright and ask
the user before proceeding.
$marker_end
EOF
        log "copilot: appended block to $f"
    else
        log "copilot: block already present in $f"
    fi
}

wire_aider() {
    local f="$HOME/.aider.conf.yml"
    local inst="$HOME/.aider.odoo-rpc.md"
    if [[ $UNINSTALL -eq 1 ]]; then
        [[ -f "$inst" ]] && { rm "$inst"; log "aider: removed $inst"; }
        return
    fi
    cat > "$inst" <<EOF
# odoo-rpc skill (aider auto-loaded via read-file)
When the user asks about a live Odoo instance, consult $SRC/SKILL.md.
CLI: /opt/odoo_rpc.py.  Run \`/opt/odoo_rpc.py doctor\` first.
EOF
    log "aider: wrote $inst (add 'read: $inst' to $f manually if you want it auto-loaded)"
}

wire_cline() {
    # Cline (VS Code) looks for .clinerules in the project; also respects a
    # user-level file at ~/Documents/Cline/Rules/ on some setups. We provide both.
    local dirs=("$HOME/Documents/Cline/Rules" "$HOME/.config/cline/rules")
    if [[ $UNINSTALL -eq 1 ]]; then
        for d in "${dirs[@]}"; do
            [[ -f "$d/odoo-rpc.md" ]] && { rm "$d/odoo-rpc.md"; log "cline: removed $d/odoo-rpc.md"; }
        done
        return
    fi
    for d in "${dirs[@]}"; do
        mkdir -p "$d"
        cat > "$d/odoo-rpc.md" <<EOF
# odoo-rpc
Investigate and automate a live Odoo instance. Skill content lives at $SRC/.
Read $SRC/SKILL.md when the user mentions Odoo, prod, staging, xmlrpc, trace a record,
ui test, press a button, upgrade a module, or inspect a view.
Run \`/opt/odoo_rpc.py doctor\` first.
EOF
        log "cline: wrote $d/odoo-rpc.md"
    done
}

wire_generic() {
    # Catch-all: $HOME/.ai-skills/odoo-rpc
    local dest="$HOME/.ai-skills/odoo-rpc"
    if [[ $UNINSTALL -eq 1 ]]; then
        [[ -L "$dest" ]] && { rm "$dest"; log "generic: removed $dest"; }
        return
    fi
    mkdir -p "$(dirname "$dest")"
    ln -sfn "$SRC" "$dest"
    log "generic: linked $dest -> $SRC"
}

# detect what's installed
detect() {
    local p=""
    [[ -d "$HOME/.claude" ]] && p+=",claude-code"
    [[ -d "$HOME/.config/opencode" || -x "$(command -v opencode 2>/dev/null)" ]] && p+=",opencode"
    [[ -d "$HOME/.cursor" || -x "$(command -v cursor 2>/dev/null)" ]] && p+=",cursor"
    [[ -d "$HOME/.config/github-copilot" || -x "$(command -v code 2>/dev/null)" ]] && p+=",copilot"
    [[ -x "$(command -v aider 2>/dev/null)" || -f "$HOME/.aider.conf.yml" ]] && p+=",aider"
    [[ -d "$HOME/Documents/Cline" || -d "$HOME/.config/cline" ]] && p+=",cline"
    p+=",generic"
    echo "${p#,}"
}

if [[ -z "$PLATFORMS" ]]; then
    PLATFORMS="$(detect)"
    log "detected platforms: $PLATFORMS"
fi

IFS=',' read -ra PLIST <<< "$PLATFORMS"
for pl in "${PLIST[@]}"; do
    case "$pl" in
        claude-code) wire_claude_code ;;
        opencode)    wire_opencode ;;
        cursor)      wire_cursor ;;
        copilot)     wire_copilot ;;
        aider)       wire_aider ;;
        cline)       wire_cline ;;
        generic)     wire_generic ;;
        '') ;;
        *) warn "unknown platform: $pl" ;;
    esac
done

# ---------- 3. Playwright ----------
if [[ $UNINSTALL -eq 0 && $INSTALL_PW -eq 1 ]]; then
    if [[ -x "$SRC/scripts/install_playwright.sh" ]]; then
        log "running Playwright installer (pass --no-playwright to skip)"
        bash "$SRC/scripts/install_playwright.sh" || warn "Playwright install failed (optional)"
    fi
fi

log "done. Verify with: /opt/odoo_rpc.py doctor --pretty"
