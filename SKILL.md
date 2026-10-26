---
name: odoo-rpc
description: Investigate, configure, and UI-test a remote Odoo instance (v13+) from the shell. XML-RPC CLI plus Playwright harness. Use whenever the user wants to query/update data on a live Odoo server, debug a configuration or data corruption, trace why a record changed, test a form or button in the real UI, predict a layout break from view arch, or help a functional implementer walk a flow. Trigger phrases include "remote odoo", "live server", "prod", "staging", "xmlrpc", "fetch from odoo", "check field X on server", "run method on odoo", "test the UI on", "press button on", "load the form view", "simulate onchange", "ui test", "backend test", "why did this record change", "trace this record", "investigate record", "regenerate journal entry", "post payslip", "upgrade module", "see what changed on prod", "playwright test odoo".
---

# Odoo RPC — Functional & Technical Investigation Skill

Two tools:

1. **`/opt/odoo_rpc.py`** — XML-RPC CLI. Config at `~/.odoo_rpc/config.json` (chmod 600). Full command list below.
2. **`scripts/odoo_playwright.py`** — Headless browser harness for real UI tests (login, click, screenshot, trace). See `references/playwright.md`.

## Prime directive — be interactive

Functional implementers rarely know the model name. Developers rarely know the business flow. This skill mediates. **On every activation, do these four steps in order:**

### Step 1 — Doctor check (first call, every new session)

Before anything else:
```
python3 /opt/odoo_rpc.py --pretty doctor
```

Output is JSON with `ok`, `issues`, `info`. For each issue, decide what to ask the user via **AskUserQuestion**:

| Issue id | What to do |
|--|--|
| `no_config` / `no_aliases` | Ask: "Do you have an Odoo server to connect to? If yes, I need URL, email, password (and DB name — I can discover it from the URL). " Then run `config add`. |
| `default_unreachable` | Ask: "Default alias failed to auth — password changed? Want to re-add it?" |
| `no_playwright` | Only matters if the user asked for a UI test / screenshot / click. If they did, ask: "UI tests need Playwright + Chromium (~200 MB), one-time install. Install now? Y/N" — on yes run `bash /opt/odoo-rpc/scripts/install_playwright.sh`. |
| `no_chromium` | Silently run `~/.odoo_rpc/venv/bin/playwright install chromium`. |
| `playwright_broken` | Ask: "Playwright is broken — re-run installer? Y/N" |

Doctor is informational — never block the user over a `severity: info` issue that doesn't match their task.

### Step 2 — Reflect the request in Odoo-domain terms

One line, not a lecture:
> You want X — in Odoo that's model `foo.bar`, action `action_do_x`, state transition `draft -> confirmed`. Confirm?

### Step 3 — Ask one targeted question if ambiguous

Use **AskUserQuestion** when:
- User said "the batch" / "the invoice" / "the record" without an id → ask which.
- Error traceback not pasted → ask for it.
- Prod vs staging unclear → ask (default: never assume prod).
- Multiple aliases exist and request didn't name one → ask which alias.
- Before a destructive write (delete, mass update, cancel many records) → confirm scope.

**One question at a time.** Resolve, then ask the next. Never fire three AskUserQuestion in a row.

### Step 4 — Inspect the technical object first

Before any write or theory, run:
- `fields MODEL --like <keyword>` to confirm field names on this Odoo version.
- `view MODEL --view-type form --arch-only` or `view_fields MODEL` to see the UI.
- `read MODEL ID` (full default fields) to see current state.
- `trace MODEL ID` if the question is "why did this happen".

This is the "always analyze DB technical objects for issue investigation" rule. Never answer from assumption when a live record is one call away.

Load `references/prompt-layer.md` for the full question tree.

## Setup — once per environment

```
python3 /opt/odoo_rpc.py config add <alias> \
    --url https://host --db DBNAME --login user@x.com --password 'XXX' [--insecure] [--set-default]
```

Don't know the DB name? Discover it:
```
python3 /opt/odoo_rpc.py --pretty db-list https://host.odoo.com
```

Verify:
```
python3 /opt/odoo_rpc.py --alias <alias> check
```

Config management: `config list`, `config rm <alias>`, `config set-default <alias>`.

Playwright setup (first UI-test run only):
```
bash /home/hp/.claude/skills/odoo-rpc/scripts/install_playwright.sh
```

## Command map

Global flags: `--alias NAME` (-a), `--pretty`. IDS = single int or JSON list. Domains/values accept JSON (preferred) or Python literals.

### Read / inspect

| Command | Purpose |
|--|--|
| `check` | authenticate + print server version |
| `search MODEL [--domain --limit --offset --order]` | ids only |
| `search_count MODEL [--domain]` | count |
| `read MODEL IDS [--fields a,b]` | read records |
| `search_read MODEL [--domain --fields --limit --offset --order]` | search + read |
| `fields_get MODEL [--attributes]` | raw schema |
| `fields MODEL [--like TEXT]` | compact field list with filter — your go-to for "what fields exist" |
| `models [--like TEXT]` | list `ir.model` entries |
| `name_search MODEL [--name --operator --limit --args-domain --context]` | M2O autocomplete |
| `menus [--like TEXT]` | user-visible menu tree |
| `xmlid module.name` | resolve xmlid |
| `action [--xmlid m.n \| --model M --id N]` | resolve `ir.actions.*` |

### Investigation (power helpers)

| Command | Purpose |
|--|--|
| `trace MODEL ID [--limit N]` | chatter + tracking values + nearby module upgrades. **Default tool for "why did this change?"** |
| `diff MODEL ID1 ID2 [--fields]` | field-by-field diff between two records |
| `refs MODEL ID [--sample N]` | reverse FK lookup — every M2O referencing this record |
| `view-chain MODEL [--view-type]` | every `ir.ui.view` in the inheritance chain |
| `rules MODEL` | active `ir.rule` record rules |
| `access MODEL` | read/write/create/unlink access for current user |
| `db-list URL [--insecure]` | discover DB names on a host |

### View / UI

| Command | Purpose |
|--|--|
| `view MODEL [--view-type --view-id --xmlid --context --arch-only]` | load view arch + fields |
| `view_fields MODEL [--view-type --view-id --context]` | parsed fields + buttons w/ modifiers — **input for a UI test** |
| `onchange MODEL --values '{..}' [--field --spec --context]` | simulate a form onchange |
| `default_get MODEL [--fields --context]` | server defaults for a new record |
| `button MODEL METHOD IDS [--context]` | press an `object` button — `model.method(ids, context=...)` |

### Write (prod-risky — snapshot + confirm)

| Command | Purpose |
|--|--|
| `create MODEL VALUES` | create |
| `write MODEL IDS VALUES` | update |
| `unlink MODEL IDS` | delete |
| `call MODEL METHOD [--args --kwargs]` | arbitrary `execute_kw` |
| `snapshot MODEL IDS --to FILE [--fields]` | dump records to JSON (safety net) |
| `restore --from FILE [--model --skip]` | write values back from a snapshot |
| `report XMLID IDS --save FILE` | render a QWeb report to PDF |
| `install NAMES --yes` | `button_immediate_install` by comma-separated names |
| `upgrade NAMES --yes` | `button_immediate_upgrade` by comma-separated names |

## Guardrails — the three habits

1. **Snapshot before destructive writes.**
   ```
   python3 /opt/odoo_rpc.py -a prod snapshot hr.salary.rule '[41,42,43,44,45,47]' --to /tmp/pre_fix.json
   ```
   Costs nothing. `restore --from /tmp/pre_fix.json` reverses it in one line.

2. **Trace before you theorize.** Any "why is this field wrong / why did X change / who touched Y" question starts with `trace MODEL ID`. The `nearby_module_upgrades` block catches migration-time corruption.

3. **Confirm every prod write.** Show the model, ids, and vals before firing. Never chain `write` + `button` to post/validate in the same step — split them so the user acknowledges between.

## When to load reference files

Reference files are loaded **on demand**, not every turn.

| File | Load when |
|--|--|
| `references/prompt-layer.md` | user request is ambiguous or you're drafting a question |
| `references/investigation.md` | debugging a data issue, a server error, a stuck state, a vanishing record |
| `references/layout-prediction.md` | user asks "will this view break", or UI test fails on an element |
| `references/playwright.md` | real UI test (login, button opens a wizard, screenshot, anything RPC can't do) |
| `references/common-models.md` | user mentions a domain (payroll, accounting, sales, inventory, HR, purchase, project) and you need the common model/field/button map |
| `references/recipes.md` | ready-to-run playbooks (regenerate payslip JE, fix bad analytic distribution, re-post failed moves, cross-company analytic clean-up) |

## Common pitfalls

- **Version drift.** Fields vanish or rename across major versions (v18 → v19 dropped `hr.payslip.contract_id`, `hr.payslip.number`). If `read` dies on a field, run `fields MODEL` first.
- **Multi-company views.** Pass `--context '{"allowed_company_ids":[N],"company_id":N}'` to `view`, `button`, `onchange` — else you load the wrong company's form.
- **Buttons of `type="action"`** open a client-side wizard — `button` cannot press them. Resolve via `action --xmlid`, create the wizard model, write values, press its button. Or use Playwright.
- **`fields.Json` fields** cannot be filtered on inner keys from a domain. Fetch, filter client-side.
- **`action_post` on payroll moves** cascades through many `_post` overrides (sale, loans, assets, SA edi, extract, reports, accountant). An error from any override blocks the post — read the traceback top-to-bottom to find the real cause.
- **Odoo 19 payroll `analytic_distribution`** is `fields.Json`. Correct shape: `{"<account_id>": pct}` or `{"id1,id2": pct}`. Any other shape is corruption.

## Session trace — what good investigation looks like

The hr.payslip v19 migration bug this skill was built against:

1. User: "post failed on payslip 734".
2. `trace hr.payslip 734` → chatter shows `move_state` tracked `'' -> draft` at validation, but current `move_id = False` → move created then deleted.
3. `search_read account.move --domain [["journal_id","=",64],["date",">=","2026-07-01"]]` → no move references the employee.
4. Error traceback blames `_prepare_analytic_distribution_line` on `int('{"1": 11}')`. `search_read hr.salary.rule --domain [["analytic_distribution","!=",false]]` → 6 rules on struct 4 with corrupted key `{"1": 11}`.
5. `read hr.salary.rule [41] --fields write_uid,write_date` → OdooBot, 2026-10-26 18:22:35.
6. `search_read ir.module.module --domain [["write_date",">=","2026-10-26 18:00:00"]]` → `l10n_sa_hr_payroll` upgraded 18:22:24, 10s before the write.
7. Conclusion: SaaS migration bug, not custom code. Fix: `write hr.salary.rule [41,42,43,44,45,47] {"analytic_distribution": false}` + clear 19 draft move_lines with the bad key. Snapshot first.

Every step is a single CLI call. The pattern — **chatter → tracking → upstream cause → neighbour timestamps → fix** — is in `references/investigation.md`.

## Output

Default: compact JSON on stdout. `--pretty` indents. Pipe into `jq` or `python3 -c '...'` for filtering. XML-RPC faults go to stderr with exit code 2.
