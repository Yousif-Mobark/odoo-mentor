#!/usr/bin/env python3
"""Playwright harness for the odoo-rpc skill.

Reads the same ~/.odoo_rpc/config.json aliases as odoo_rpc.py, logs in via the
web client, and exposes a few primitives for UI tests: open a record, take a
screenshot, click a selector, press a button by label, record a trace.

Requires:  pip install playwright && playwright install chromium
           (use scripts/install_playwright.sh)

Examples:
    odoo_playwright.py -a prod screenshot --model hr.payslip --id 767 --to /tmp/slip.png
    odoo_playwright.py -a prod screenshot --url /odoo/payslips/767 --to /tmp/slip.png --lang ar_001
    odoo_playwright.py -a prod click --model hr.payslip --id 767 --button "Print"
    odoo_playwright.py -a prod form-audit --model hr.payslip --id 767 --to /tmp/audit.json
    odoo_playwright.py -a prod trace --url /odoo/payslips/767 --to /tmp/trace.zip
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeout
except ImportError:
    print("playwright not installed. Run scripts/install_playwright.sh first.", file=sys.stderr)
    sys.exit(2)

CONFIG_FILE = Path(os.environ.get("ODOO_RPC_HOME", str(Path.home() / ".odoo_rpc"))) / "config.json"


def load_alias(name: str | None) -> dict:
    cfg = json.loads(CONFIG_FILE.read_text())
    if not name:
        name = os.environ.get("ODOO_RPC_ALIAS") or cfg.get("default")
    if not name:
        sys.exit("No alias. Use --alias or set a default via `odoo_rpc.py config set-default`.")
    entry = cfg.get("aliases", {}).get(name)
    if not entry:
        sys.exit(f"Unknown alias: {name}")
    return entry


def login(page: Page, entry: dict, lang: str | None = None) -> None:
    url = entry["url"].rstrip("/")
    page.goto(f"{url}/web/login", wait_until="domcontentloaded")
    page.fill("input[name=login]", entry["login"])
    page.fill("input[name=password]", entry["password"])
    # Odoo may show a database selector on multi-db hosts; fill if present.
    try:
        page.wait_for_selector("select[name=db]", timeout=1500)
        page.select_option("select[name=db]", entry["db"])
    except PlaywrightTimeout:
        pass
    page.click("button[type=submit]")
    page.wait_for_url("**/web**", timeout=30_000)
    if lang:
        # Set lang via /web?debug=1 is overkill; use res.lang preference call instead,
        # but easier: use ?lang=xx on URL for subsequent navigation.
        page._odoo_lang = lang  # type: ignore[attr-defined]


def goto_record(page: Page, entry: dict, model: str | None, rec_id: int | None,
                raw_url: str | None, lang: str | None = None) -> None:
    url = entry["url"].rstrip("/")
    if raw_url:
        path = raw_url if raw_url.startswith("http") else f"{url}{raw_url}"
    elif model and rec_id:
        # Odoo 17+ uses /odoo/<model-shortcut>/<id>; fallback to action-based URL.
        path = f"{url}/odoo/action-base.action_ui/{model}/{rec_id}"
    else:
        sys.exit("Need either --url or --model+--id")
    if lang:
        sep = "&" if "?" in path else "?"
        path = f"{path}{sep}lang={lang}"
    page.goto(path, wait_until="networkidle", timeout=45_000)
    page.wait_for_selector(".o_form_view, .o_list_view, .o_kanban_view, .o_action", timeout=30_000)


def cmd_screenshot(args):
    entry = load_alias(args.alias)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        ctx = browser.new_context(
            viewport={"width": args.width, "height": args.height},
            locale=args.lang or "en-US",
        )
        page = ctx.new_page()
        login(page, entry, lang=args.lang)
        goto_record(page, entry, args.model, args.id, args.url, lang=args.lang)
        if args.wait_selector:
            page.wait_for_selector(args.wait_selector, timeout=15_000)
        page.screenshot(path=args.to, full_page=args.full_page)
        print(f"Saved {args.to}")
        browser.close()


def cmd_click(args):
    entry = load_alias(args.alias)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        ctx = browser.new_context(viewport={"width": args.width, "height": args.height})
        page = ctx.new_page()
        login(page, entry)
        goto_record(page, entry, args.model, args.id, args.url)
        if args.button:
            # Try role=button first (OWL), fall back to text match.
            try:
                page.get_by_role("button", name=args.button, exact=False).first.click(timeout=5_000)
            except PlaywrightTimeout:
                page.get_by_text(args.button, exact=False).first.click()
        elif args.selector:
            page.click(args.selector)
        else:
            sys.exit("Need --button or --selector")
        if args.wait_for:
            page.wait_for_selector(args.wait_for, timeout=15_000)
        if args.screenshot_after:
            page.screenshot(path=args.screenshot_after, full_page=True)
            print(f"Saved {args.screenshot_after}")
        browser.close()


def cmd_form_audit(args):
    """Dump every visible field + button on a form, with its current value and modifiers.
    Useful to confirm a form actually shows what the server view says it should."""
    entry = load_alias(args.alias)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        ctx = browser.new_context(viewport={"width": args.width, "height": args.height})
        page = ctx.new_page()
        login(page, entry)
        goto_record(page, entry, args.model, args.id, args.url)
        page.wait_for_selector(".o_form_view", timeout=15_000)

        data = page.evaluate("""() => {
            const walk = (root) => {
                const fields = [];
                for (const f of root.querySelectorAll('.o_field_widget[name]')) {
                    fields.push({
                        name: f.getAttribute('name'),
                        type: f.className.match(/o_field_(\\w+)/)?.[1],
                        value: f.innerText.trim().slice(0, 200),
                        invisible: f.offsetParent === null,
                    });
                }
                const buttons = [];
                for (const b of root.querySelectorAll('.o_form_view button[name], .o_cp_action_menus button')) {
                    buttons.push({
                        name: b.getAttribute('name'),
                        type: b.getAttribute('type'),
                        label: b.innerText.trim(),
                        disabled: b.disabled,
                        visible: b.offsetParent !== null,
                        classes: b.className,
                    });
                }
                const chatterMsgs = Array.from(document.querySelectorAll('.o-mail-Message'))
                    .slice(0, 10)
                    .map(m => m.innerText.trim().slice(0, 300));
                return { fields, buttons, chatter_preview: chatterMsgs };
            };
            return walk(document);
        }""")
        Path(args.to).write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"Wrote {args.to}")
        browser.close()


def cmd_trace(args):
    """Record a Playwright trace (clicks, screenshots, network) over a navigation.
    View with:  playwright show-trace <file.zip>"""
    entry = load_alias(args.alias)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        ctx = browser.new_context(viewport={"width": args.width, "height": args.height})
        ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = ctx.new_page()
        login(page, entry)
        goto_record(page, entry, args.model, args.id, args.url)
        if args.click:
            try:
                page.get_by_role("button", name=args.click, exact=False).first.click(timeout=5_000)
            except PlaywrightTimeout:
                page.get_by_text(args.click, exact=False).first.click()
            page.wait_for_load_state("networkidle", timeout=15_000)
        ctx.tracing.stop(path=args.to)
        print(f"Saved trace to {args.to}  (view: playwright show-trace {args.to})")
        browser.close()


def cmd_record(args):
    """Launch codegen (headful) to record a UI test and emit Python Playwright code."""
    entry = load_alias(args.alias)
    url = entry["url"].rstrip("/") + "/web/login"
    import subprocess
    subprocess.run(["playwright", "codegen", "--target", "python", "-o", args.to, url], check=True)
    print(f"Saved recorded script to {args.to}")


def build_parser():
    p = argparse.ArgumentParser(prog="odoo_playwright", description="Playwright UI harness for Odoo")
    p.add_argument("--alias", "-a")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--model")
        sp.add_argument("--id", type=int)
        sp.add_argument("--url", help="Raw path or full URL (overrides --model/--id)")
        sp.add_argument("--width", type=int, default=1366)
        sp.add_argument("--height", type=int, default=768)
        sp.add_argument("--headed", action="store_true", help="Show the browser (default headless)")

    sc = sub.add_parser("screenshot", help="Open a record and save a PNG")
    common(sc)
    sc.add_argument("--to", required=True)
    sc.add_argument("--full-page", action="store_true")
    sc.add_argument("--wait-selector", help="Wait for this selector before snapping")
    sc.add_argument("--lang", help="Locale, e.g. ar_001")
    sc.set_defaults(func=cmd_screenshot)

    ck = sub.add_parser("click", help="Click a button by label or a CSS selector on a record")
    common(ck)
    ck.add_argument("--button", help="Button label text")
    ck.add_argument("--selector", help="CSS selector")
    ck.add_argument("--wait-for", help="Selector to wait on after the click")
    ck.add_argument("--screenshot-after", help="Snap PNG after the click")
    ck.set_defaults(func=cmd_click)

    fa = sub.add_parser("form-audit", help="Dump visible fields + buttons + chatter preview on a form")
    common(fa)
    fa.add_argument("--to", required=True)
    fa.set_defaults(func=cmd_form_audit)

    tr = sub.add_parser("trace", help="Record a Playwright trace file")
    common(tr)
    tr.add_argument("--to", required=True)
    tr.add_argument("--click", help="Optional button label to click within the trace")
    tr.set_defaults(func=cmd_trace)

    rc = sub.add_parser("record", help="Launch codegen to record a UI script interactively")
    rc.add_argument("--to", required=True, help="Where to write the recorded Python script")
    rc.set_defaults(func=cmd_record)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
