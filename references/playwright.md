# Playwright UI testing

The RPC layer tests what the server returns. Playwright tests what the user sees. Use it when the symptom hinges on the browser: client-side wizards, RTL rendering, modal popups, kanban drags, chatter widgets, PDF viewers.

The harness is at `/home/hp/.claude/skills/odoo-rpc/scripts/odoo_playwright.py`. It reads the same alias config as `/opt/odoo_rpc.py`.

## One-time install

```
bash /home/hp/.claude/skills/odoo-rpc/scripts/install_playwright.sh
```

This creates a venv at `~/.odoo_rpc/venv`, installs playwright + Chromium. Idempotent — safe to rerun.

To run the harness afterwards:
```
~/.odoo_rpc/venv/bin/python /home/hp/.claude/skills/odoo-rpc/scripts/odoo_playwright.py --help
```

(Or `source ~/.odoo_rpc/venv/bin/activate` then call `python …` directly.)

## Commands

### `screenshot` — see what the user sees
```
odoo_playwright.py -a prod screenshot \
    --model hr.payslip --id 767 \
    --to /tmp/slip.png --full-page
```
Options:
- `--url /odoo/payslips/767` — if you have the direct link (overrides `--model` + `--id`)
- `--width 1366 --height 768` — viewport (default)
- `--wait-selector .o_form_sheet` — wait for a specific element before snapping
- `--lang ar_001` — switch locale (critical for RTL layout audits)
- `--headed` — show the browser (default headless)

### `click` — press a button and see the result
```
odoo_playwright.py -a prod click \
    --model hr.payslip --id 767 \
    --button "Print" \
    --wait-for ".modal" \
    --screenshot-after /tmp/after_print.png
```
Button matching tries OWL `role=button` first, then text fallback. For non-button clicks pass `--selector '.o_button_strong'`.

### `form-audit` — compare what the view says vs what the user gets
```
odoo_playwright.py -a prod form-audit \
    --model hr.payslip --id 767 \
    --to /tmp/audit.json
```
Dumps visible fields (with their rendered text and whether they're in the viewport), visible buttons (with class/disabled/visibility), and the first 10 chatter messages. Diff this against `view_fields` output from the RPC CLI to find mismatches.

### `trace` — record a replay of a browser session
```
odoo_playwright.py -a prod trace \
    --model hr.payslip --id 767 \
    --click "Validate" \
    --to /tmp/trace.zip
```
Then view with:
```
~/.odoo_rpc/venv/bin/playwright show-trace /tmp/trace.zip
```
Shows screenshots, DOM snapshots, network requests, console errors — full forensic replay.

### `record` — interactively capture a flow
```
odoo_playwright.py -a prod record --to /tmp/my_test.py
```
Opens a headful Chromium with codegen. Clicks you make become Python Playwright code written to `/tmp/my_test.py`.

## When to pick Playwright over RPC

| Task | Use |
|--|--|
| Confirm button is visible / enabled | `view_fields` (fast) *or* `form-audit` (ground truth) |
| Press a `type="object"` button | `button MODEL METHOD IDS` (RPC) |
| Press a `type="action"` button (opens wizard) | Playwright `click` (RPC can only resolve the action, not run the wizard flow) |
| Verify a PDF prints | `report xmlid IDS --save FILE` (RPC) |
| Verify a PDF prints visually in the browser preview | Playwright `click` with `--wait-for ".o_pdf_viewer"` + screenshot |
| Reproduce an RTL layout break | Playwright `screenshot --lang ar_001` |
| Prove an error is client-side only | Playwright `trace` — Console logs show the OWL error that never reaches the server |
| Audit chatter rendering | Playwright `form-audit` (chatter is client-side rendered from `mail.message` RPC) |
| Simulate a user filling + saving a form | Playwright `record` → tweak the generated script |

## Writing a reusable test

The recorded script output is a plain `page.*` script. Wrap it in a Python function so it can be rerun. Example:

```python
# tests/test_payslip_post.py
from playwright.sync_api import sync_playwright

def test_payslip_post(entry, payslip_id):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(f"{entry['url']}/web/login")
        page.fill("input[name=login]", entry["login"])
        page.fill("input[name=password]", entry["password"])
        page.click("button[type=submit]")
        page.wait_for_url("**/web**")
        page.goto(f"{entry['url']}/odoo/payslips/{payslip_id}")
        page.get_by_role("button", name="Validate").click()
        page.wait_for_selector(".o_form_statusbar [data-value='done']")
        browser.close()
```

## Gotchas

- **Login throttling.** Running the harness in a tight loop will hit Odoo's login rate limit. Pool with `browser_context` reuse across tests or add a sleep.
- **Multi-company accounts.** The login lands on the user's default company. To test in a different one, either switch via `/web#active_id=…` or set `allowed_company_ids` via RPC on the user record before launching.
- **Studio-added fields** have `data-name` attribute instead of `name`. `form-audit` catches both.
- **The chatter is lazy-loaded.** `form-audit` waits for `.o_form_view` but not for chatter. Add `page.wait_for_selector(".o-mail-Thread")` before auditing chatter.
- **`networkidle` on dashboards hangs** because of long-poll channels. Use `--wait-selector` with a specific element instead.
