# odoo-rpc — Claude Code skill

An investigation and automation skill for working with a live Odoo instance (v13+) from the terminal. Pairs a batteries-included XML-RPC CLI with a Playwright UI harness so Claude (and you) can:

- Query, update, create, delete records on a running Odoo server.
- Trace *why* a record changed — chatter, tracking values, nearby module upgrades.
- Snapshot & restore records before destructive writes.
- Load view arches, predict layout breaks, and audit forms in a real browser.
- Press buttons, run onchanges, resolve xmlids, render reports to PDF, upgrade modules.
- Run real UI tests: screenshot, click, trace, form-audit, codegen.

Built against Odoo 13 → 19 (community & enterprise), tested on Odoo 19 SaaS.

## Install — one command, all AI assistants

```bash
sudo cp -r /path/to/odoo-rpc /opt/odoo-rpc
bash /opt/odoo-rpc/install.sh
```

The installer:
1. Symlinks `/opt/odoo_rpc.py` → `/opt/odoo-rpc/bin/odoo_rpc.py`.
2. Detects installed AI assistants (Claude Code, OpenCode, Cursor, GitHub Copilot, Aider, Cline) and wires the skill into each one. All installations point back to `/opt/odoo-rpc/` — one source of truth.
3. Installs Playwright + Chromium into `~/.odoo_rpc/venv` (skip with `--no-playwright`).

Options:
```bash
bash /opt/odoo-rpc/install.sh                           # auto-detect everything
bash /opt/odoo-rpc/install.sh --platform claude-code,cursor
bash /opt/odoo-rpc/install.sh --no-playwright
bash /opt/odoo-rpc/install.sh --uninstall               # removes all adapters
```

Verify:
```bash
/opt/odoo_rpc.py doctor --pretty
```

The CLI stores connection aliases in `~/.odoo_rpc/config.json` (chmod 600).

Point it at a server:

```bash
python3 /opt/odoo_rpc.py config add prod \
    --url https://host.odoo.com --db DBNAME \
    --login user@example.com --password 'secret' \
    --set-default
python3 /opt/odoo_rpc.py check
```

Don't know the DB name? Discover it:
```bash
python3 /opt/odoo_rpc.py --pretty db-list https://host.odoo.com
```

## What's inside

```
odoo-rpc/
├── SKILL.md                              # Skill prime directive (loaded on trigger)
├── README.md                             # This file
├── CHANGELOG.md
├── LICENSE
├── bin/
│   └── odoo_rpc.py                       # XML-RPC CLI (also deployable to /opt/)
├── scripts/
│   ├── install_playwright.sh             # One-shot venv + Chromium install
│   └── odoo_playwright.py                # UI harness: screenshot/click/trace/audit
├── references/                           # On-demand deep-dives
│   ├── prompt-layer.md                   # How to translate functional asks → RPC calls
│   ├── investigation.md                  # Technical-object investigation protocol
│   ├── layout-prediction.md              # Reading view arch for layout breaks
│   ├── playwright.md                     # UI test guide
│   ├── common-models.md                  # Business-term → model map
│   └── recipes.md                        # Ready-to-run playbooks (JE regen, bad analytic, cross-company, etc.)
└── examples/                             # Shell session transcripts
```

## Design principles

1. **Technical analysis before action.** Every answer is grounded in a live inspection of `ir.model`, `ir.ui.view`, `mail.message`, or `ir.module.module`. The skill actively discourages pattern-matched guesses.
2. **Functional + technical in one tool.** Business implementers get a prompt layer that reframes requests in Odoo terms; developers get `trace`, `diff`, `refs`, `snapshot`, raw `call`.
3. **Safe writes.** Snapshot first; one `restore --from FILE` unwinds. Confirm every prod write.
4. **Composable.** The CLI emits JSON by default — pipe into `jq`, `python3 -c`, `awk`. The Playwright harness is a Python script, not a black-box MCP server.
5. **Teaches the model to ask better questions.** `references/prompt-layer.md` is a question tree keyed by common functional phrasings.

## Example — real-world session

A user hit `_prepare_analytic_distribution_line` crashing at `int('{"1": 11}')` on an Odoo 19 SaaS tenant. One session:

```bash
# 1. Confirm the record state
python3 /opt/odoo_rpc.py -a prod --pretty read hr.payslip 767

# 2. Find who tracked what, when, and what modules upgraded nearby
python3 /opt/odoo_rpc.py -a prod --pretty trace hr.payslip 734

# 3. Scope: how many rules carry the bad distribution?
python3 /opt/odoo_rpc.py -a prod --pretty search_read hr.salary.rule \
    --domain '[["analytic_distribution","!=",false]]' \
    --fields name,code,struct_id,analytic_distribution,write_uid,write_date

# 4. Confirm the upstream cause
python3 /opt/odoo_rpc.py -a prod --pretty search_read ir.module.module \
    --domain '[["write_date",">=","2026-10-26 18:00:00"]]' \
    --fields name,write_date,write_uid --order write_date

# 5. Snapshot before fix
python3 /opt/odoo_rpc.py -a prod snapshot hr.salary.rule '[41,42,43,44,45,47]' \
    --to /tmp/rules_pre.json

# 6. Patch
python3 /opt/odoo_rpc.py -a prod write hr.salary.rule '[41,42,43,44,45,47]' \
    '{"analytic_distribution": false}'
```

Diagnosed in 6 calls. Full narrative in `SKILL.md`.

## When to pick each tool

| Need | Reach for |
|--|--|
| Read / write any record | `/opt/odoo_rpc.py` |
| "Why did this change?" | `odoo_rpc.py trace` |
| Compare two records | `odoo_rpc.py diff` |
| Find who/what references a record | `odoo_rpc.py refs` |
| Confirm a view's buttons / modifiers | `odoo_rpc.py view_fields` |
| Press an `object` button | `odoo_rpc.py button` |
| Press a client-side (`action`) button | `odoo_playwright.py click` |
| Screenshot the real UI (RTL, modal, kanban) | `odoo_playwright.py screenshot` |
| Record a UI test interactively | `odoo_playwright.py record` |
| Render a QWeb report to PDF | `odoo_rpc.py report` |
| Install / upgrade a module | `odoo_rpc.py install` / `upgrade` |

## Contributing

PRs welcome. Keep each command single-purpose, JSON-first for machine consumers, and documented in `SKILL.md`'s command map.

## License

MIT. See `LICENSE`.
