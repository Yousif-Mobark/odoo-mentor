# Changelog

## 0.4.0 — 2026-10-26

- Playwright harness rewritten as persistent daemon + client:
  - `serve` keeps one Chromium instance alive, listens on `~/.odoo_rpc/pw.sock`.
  - `send '<json>'` sends one command, prints JSON response — no browser relaunch.
  - `status` / `stop` for lifecycle management.
  - Authentication via `/web/session/authenticate` + cookie injection — no UI login form.
  - Human-like pacing: `--slow-mo 150` by default, scroll-into-view + hover before every click.
  - Command vocabulary: `goto`, `wait`, `html`, `outer`, `text`, `attrs`, `click`, `click_label`, `fill`, `type`, `press`, `eval`, `url`, `title`, `screenshot`, `back`, `forward`, `reload`, `cookies`, `stop`.
  - One-shot `screenshot` kept for compatibility.
- SKILL.md adds **Step 5 — Auto-suggest a UI test after each task**. Every mutating task ends with a pre-filled AskUserQuestion offering to verify in the real UI.

## 0.3.0 — 2026-10-26

- Canonical home moved to `/opt/odoo-mentor/`. Every platform adapter now points back to this directory — one source of truth.
- `install.sh` — one-command multi-platform installer with auto-detection and `--uninstall`. Supported targets: Claude Code, OpenCode, Cursor, GitHub Copilot (VS Code), Aider, Cline, plus a generic `~/.ai-skills/` catch-all.
- New CLI `doctor` command — environment status check (aliases, Playwright presence, Chromium path, skill locations). Returns JSON with `issues` for interactive handling.
- SKILL.md rewritten as an **interactive** prime directive: run `doctor` first every session, use AskUserQuestion for missing config/Playwright/ambiguity, reflect in Odoo terms, inspect technical objects before writing.
- `install.sh --no-playwright` skips the Chromium download (~200 MB) for quick installs.

## 0.2.0 — 2026-10-26

- Repositioned skill for functional implementers + technical mixed audience.
- New CLI commands:
  - `db-list URL` — discover DB names on a host without any config.
  - `fields MODEL [--like]` — compact field reference (name/type/relation/required/string).
  - `trace MODEL ID` — chatter + tracking values + nearby module upgrades in one shot.
  - `diff MODEL ID1 ID2` — field-by-field diff of two records.
  - `refs MODEL ID` — reverse FK walk (every M2O referencing this record).
  - `view-chain MODEL [--view-type]` — list every `ir.ui.view` in the inheritance chain.
  - `rules MODEL` — active `ir.rule` record rules on a model.
  - `snapshot MODEL IDS --to FILE` + `restore --from FILE` — safety net for prod writes.
  - `report XMLID IDS --save FILE` — QWeb → PDF via HTTP session.
  - `install NAMES --yes` / `upgrade NAMES --yes` — module ops.
- New Playwright harness `scripts/odoo_playwright.py`:
  - `screenshot`, `click`, `form-audit`, `trace`, `record` subcommands.
  - Reuses the same alias config as the RPC CLI.
  - `install_playwright.sh` one-shot venv installer.
- New reference docs under `references/`:
  - `prompt-layer.md` — question tree for ambiguous functional asks.
  - `investigation.md` — technical-object investigation protocol.
  - `layout-prediction.md` — view-arch regression detection.
  - `playwright.md` — UI testing guide.
  - `common-models.md` — business-term → model map by domain.
  - `recipes.md` — ready-to-run playbooks (JE regen, bad analytic distribution, cross-company analytic, broken view, bulk salesperson reassign, etc.).
- SKILL.md rewritten with a prime-directive section (reflect → ask targeted → inspect first).
- README.md + LICENSE + this CHANGELOG for publish-readiness.

## 0.1.0 — initial

- XML-RPC CLI at `/opt/odoo_rpc.py` with config aliases, `check`, `search`, `read`, `write`, `create`, `unlink`, `fields_get`, `call`, `models`, `view`, `view_fields`, `button`, `action`, `onchange`, `default_get`, `name_search`, `menus`, `access`, `xmlid`.
- Minimal SKILL.md.
