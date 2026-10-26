#!/usr/bin/env bash
# One-shot Playwright setup for the odoo-rpc skill.
# Safe to re-run — idempotent.

set -euo pipefail

VENV="${ODOO_RPC_VENV:-$HOME/.odoo_rpc/venv}"

echo "==> Creating venv at $VENV"
python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "==> Installing playwright"
pip install --upgrade pip
pip install playwright

echo "==> Downloading Chromium browser"
playwright install chromium
playwright install-deps chromium || echo "install-deps failed (needs sudo); may still work headless"

echo "==> Done. Activate with:"
echo "    source $VENV/bin/activate"
echo
echo "Or run the harness via:"
echo "    $VENV/bin/python /home/hp/.claude/skills/odoo-rpc/scripts/odoo_playwright.py --help"
