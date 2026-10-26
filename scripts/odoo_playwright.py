#!/usr/bin/env python3
"""Odoo Playwright harness — persistent browser session with HTML/DOM-based commands.

Daemon/client model:

    # Terminal A — start the daemon (keeps browser open)
    odoo_playwright.py -a <alias> serve [--headed] [--url /odoo/payslips/767]

    # Terminal B — send commands (prints JSON response)
    odoo_playwright.py send '{"op":"goto","url":"/odoo/payslips/767"}'
    odoo_playwright.py send '{"op":"wait","selector":".o_form_sheet"}'
    odoo_playwright.py send '{"op":"html","selector":".o_statusbar_status"}'
    odoo_playwright.py send '{"op":"click_label","label":"Cancel"}'
    odoo_playwright.py send '{"op":"stop"}'

Also kept for one-shot use:
    odoo_playwright.py -a <alias> screenshot --url /odoo/payslips/767 --to out.png

Session auth: the daemon authenticates via /web/session/authenticate (same as the
RPC CLI's `report` command) and injects the session_id cookie into the browser
context. No UI login form is clicked — the browser starts already signed in.

Supported commands (op field):
  goto         {"url":"<path or full URL>"}
  wait         {"selector":"<css>", "timeout_ms": 15000}
  html         {"selector":"<css>" (default body), "limit": 20000}
      -> {"ok":true,"result":"<innerHTML truncated>"}
  text         {"selector":"<css>"}
      -> {"ok":true,"result":"<innerText>"}
  attrs        {"selector":"<css>"}  -> list of attribute dicts for all matches
  outer        {"selector":"<css>"}  -> outerHTML of first match
  click        {"selector":"<css>", "nth": 0}
  click_label  {"label":"<text>", "role":"button" (default)}
  fill         {"selector":"<css>", "value":"<text>"}
  press        {"selector":"<css>", "key":"Enter"}
  eval         {"js":"<expr returning JSON-serializable>"}
  url          -> current page URL
  title        -> current page title
  screenshot   {"path":"...", "full_page": true}
  back / forward / reload
  cookies      -> list of cookies
  stop         -> close the browser and exit the daemon
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("playwright not installed. Run scripts/install_playwright.sh or:", file=sys.stderr)
    print("  pip install --user --break-system-packages playwright && "
          "python3 -m playwright install chromium", file=sys.stderr)
    sys.exit(2)

CONFIG_FILE = Path(os.environ.get("ODOO_RPC_HOME", str(Path.home() / ".odoo_rpc"))) / "config.json"
SOCK_PATH = Path(os.environ.get("ODOO_RPC_HOME", str(Path.home() / ".odoo_rpc"))) / "pw.sock"
PID_PATH = SOCK_PATH.with_suffix(".pid")


# ---------------- config / auth ----------------

def load_alias(name: str | None) -> dict:
    if not CONFIG_FILE.exists():
        sys.exit(f"No config at {CONFIG_FILE}. Run `odoo_rpc.py config add` first.")
    cfg = json.loads(CONFIG_FILE.read_text())
    if not name:
        name = os.environ.get("ODOO_RPC_ALIAS") or cfg.get("default")
    if not name:
        sys.exit("No alias. Use --alias or set a default.")
    entry = cfg.get("aliases", {}).get(name)
    if not entry:
        sys.exit(f"Unknown alias: {name}")
    return entry


def http_authenticate(entry: dict) -> tuple[str, str]:
    """Call /web/session/authenticate and return (host, session_id).
    Lets us inject the cookie into Playwright and skip the UI login."""
    import ssl, urllib.request, urllib.parse, http.cookiejar
    url = entry["url"].rstrip("/")
    ctx = ssl._create_unverified_context() if entry.get("insecure") else None
    jar = http.cookiejar.CookieJar()
    handlers = [urllib.request.HTTPCookieProcessor(jar)]
    if ctx is not None:
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    opener = urllib.request.build_opener(*handlers)
    body = json.dumps({
        "jsonrpc": "2.0",
        "params": {"db": entry["db"], "login": entry["login"], "password": entry["password"]},
    }).encode()
    req = urllib.request.Request(f"{url}/web/session/authenticate", data=body,
                                 headers={"Content-Type": "application/json"})
    r = opener.open(req, timeout=30)
    resp = json.loads(r.read().decode())
    if resp.get("error"):
        raise RuntimeError(f"Auth failed: {resp['error']}")
    if not resp.get("result", {}).get("uid"):
        raise RuntimeError(f"Auth returned no uid: {resp}")
    host = urllib.parse.urlparse(url).hostname
    session_id = None
    for c in jar:
        if c.name == "session_id":
            session_id = c.value
            break
    if not session_id:
        raise RuntimeError("Auth OK but no session_id cookie returned")
    return host, session_id


# ---------------- daemon ----------------

def _run_op(page, op: dict) -> dict:
    o = op.get("op")
    try:
        if o == "goto":
            url = op["url"]
            if not url.startswith("http"):
                base = page.url.split("/web")[0] if "/web" in page.url else page.url.rsplit("/", 1)[0]
                # Use the browser's current origin for relative paths
                origin = page.evaluate("() => window.location.origin")
                url = origin.rstrip("/") + ("/" + url.lstrip("/"))
            page.goto(url, wait_until=op.get("wait_until", "domcontentloaded"),
                      timeout=op.get("timeout_ms", 45000))
            return {"ok": True, "result": page.url}
        if o == "wait":
            page.wait_for_selector(op["selector"], timeout=op.get("timeout_ms", 15000))
            return {"ok": True}
        if o == "html":
            sel = op.get("selector") or "body"
            limit = op.get("limit", 20000)
            html = page.locator(sel).first.inner_html(timeout=op.get("timeout_ms", 10000))
            return {"ok": True, "result": html[:limit], "truncated": len(html) > limit, "length": len(html)}
        if o == "outer":
            sel = op.get("selector") or "body"
            html = page.locator(sel).first.evaluate("el => el.outerHTML", timeout=op.get("timeout_ms", 10000))
            return {"ok": True, "result": html}
        if o == "text":
            sel = op.get("selector") or "body"
            txt = page.locator(sel).first.inner_text(timeout=op.get("timeout_ms", 10000))
            return {"ok": True, "result": txt}
        if o == "attrs":
            sel = op["selector"]
            res = page.locator(sel).evaluate_all(
                "els => els.map(e => Object.fromEntries(Array.from(e.attributes).map(a=>[a.name,a.value])))"
            )
            return {"ok": True, "result": res, "count": len(res)}
        if o == "click":
            sel = op["selector"]
            nth = op.get("nth", 0)
            loc = page.locator(sel).nth(nth)
            loc.scroll_into_view_if_needed(timeout=op.get("timeout_ms", 10000))
            loc.hover(timeout=op.get("timeout_ms", 10000))
            loc.click(timeout=op.get("timeout_ms", 10000))
            return {"ok": True}
        if o == "click_label":
            label = op["label"]
            role = op.get("role", "button")
            loc = page.get_by_role(role, name=label, exact=op.get("exact", False)).first
            loc.scroll_into_view_if_needed(timeout=op.get("timeout_ms", 10000))
            loc.hover(timeout=op.get("timeout_ms", 10000))
            loc.click(timeout=op.get("timeout_ms", 10000))
            return {"ok": True}
        if o == "fill":
            page.fill(op["selector"], op["value"], timeout=op.get("timeout_ms", 10000))
            return {"ok": True}
        if o == "type":
            loc = page.locator(op["selector"]).first
            loc.scroll_into_view_if_needed(timeout=op.get("timeout_ms", 10000))
            loc.click(timeout=op.get("timeout_ms", 10000))
            loc.press_sequentially(op["value"], delay=op.get("delay_ms", 40))
            return {"ok": True}
        if o == "press":
            page.locator(op["selector"]).first.press(op["key"], timeout=op.get("timeout_ms", 10000))
            return {"ok": True}
        if o == "eval":
            res = page.evaluate(op["js"])
            return {"ok": True, "result": res}
        if o == "url":
            return {"ok": True, "result": page.url}
        if o == "title":
            return {"ok": True, "result": page.title()}
        if o == "screenshot":
            path = op["path"]
            page.screenshot(path=path, full_page=op.get("full_page", False))
            return {"ok": True, "result": path}
        if o == "back":
            page.go_back(timeout=op.get("timeout_ms", 15000)); return {"ok": True, "result": page.url}
        if o == "forward":
            page.go_forward(timeout=op.get("timeout_ms", 15000)); return {"ok": True, "result": page.url}
        if o == "reload":
            page.reload(timeout=op.get("timeout_ms", 15000)); return {"ok": True, "result": page.url}
        if o == "cookies":
            return {"ok": True, "result": page.context.cookies()}
        if o == "stop":
            return {"ok": True, "result": "stopping"}
        return {"ok": False, "error": f"unknown op: {o}"}
    except PlaywrightTimeout as e:
        return {"ok": False, "error": f"TimeoutError: {e}", "url": page.url}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "url": page.url}


def cmd_serve(args):
    entry = load_alias(args.alias)
    print(f"[+] authenticating against {entry['url']} as {entry['login']}")
    host, session_id = http_authenticate(entry)
    print(f"[+] got session_id, host={host}")

    SOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SOCK_PATH.exists():
        SOCK_PATH.unlink()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(SOCK_PATH))
    srv.listen(5)
    SOCK_PATH.chmod(0o600)
    PID_PATH.write_text(str(os.getpid()))
    print(f"[+] daemon listening on {SOCK_PATH}")

    stop_evt = threading.Event()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed, slow_mo=args.slow_mo)
        ctx = browser.new_context(
            viewport={"width": args.width, "height": args.height},
            locale=args.lang or "en-US",
        )
        ctx.add_cookies([{
            "name": "session_id", "value": session_id,
            "domain": host, "path": "/", "httpOnly": True, "secure": True,
        }])
        page = ctx.new_page()

        start_url = args.url or "/odoo"
        if not start_url.startswith("http"):
            start_url = entry["url"].rstrip("/") + start_url
        print(f"[+] opening {start_url}")
        page.goto(start_url, wait_until="domcontentloaded", timeout=45_000)
        print(f"[+] ready. Current URL: {page.url}")

        while not stop_evt.is_set():
            try:
                srv.settimeout(1.0)
                try:
                    conn, _ = srv.accept()
                except socket.timeout:
                    continue
                with conn:
                    conn.settimeout(60)
                    buf = b""
                    while b"\n" not in buf:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        buf += chunk
                    if not buf:
                        continue
                    try:
                        op = json.loads(buf.decode().strip())
                    except Exception as e:
                        conn.sendall((json.dumps({"ok": False, "error": f"bad json: {e}"}) + "\n").encode())
                        continue
                    resp = _run_op(page, op)
                    conn.sendall((json.dumps(resp, default=str, ensure_ascii=False) + "\n").encode())
                    if op.get("op") == "stop":
                        stop_evt.set()
                        break
            except KeyboardInterrupt:
                stop_evt.set()
                break

        browser.close()

    try:
        SOCK_PATH.unlink()
    except FileNotFoundError:
        pass
    try:
        PID_PATH.unlink()
    except FileNotFoundError:
        pass
    print("[+] daemon stopped")


def cmd_send(args):
    if not SOCK_PATH.exists():
        sys.exit(f"No daemon running (expected {SOCK_PATH}). Start one with: "
                 f"odoo_playwright.py -a <alias> serve")
    if args.script:
        lines = Path(args.script).read_text().splitlines()
        payloads = [l for l in lines if l.strip() and not l.strip().startswith("#")]
    else:
        payloads = [args.cmd]
    for p in payloads:
        try:
            op = json.loads(p)
        except Exception as e:
            print(json.dumps({"ok": False, "error": f"bad json: {e}"}))
            sys.exit(2)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(args.timeout)
        s.connect(str(SOCK_PATH))
        s.sendall((json.dumps(op) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        s.close()
        line = buf.decode().strip()
        if args.pretty:
            try:
                print(json.dumps(json.loads(line), indent=2, ensure_ascii=False))
            except Exception:
                print(line)
        else:
            print(line)


def cmd_stop(args):
    if not SOCK_PATH.exists():
        print("no daemon running"); return
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(str(SOCK_PATH))
        s.sendall(b'{"op":"stop"}\n')
        s.recv(4096)
        s.close()
    except Exception:
        pass
    print("stop signal sent")


def cmd_status(args):
    running = SOCK_PATH.exists()
    pid = None
    if PID_PATH.exists():
        try:
            pid = int(PID_PATH.read_text().strip())
        except Exception:
            pass
    print(json.dumps({"running": running, "socket": str(SOCK_PATH), "pid": pid}))


# ---------------- one-shot (kept for compatibility) ----------------

def cmd_screenshot_oneshot(args):
    """One-shot screenshot. Starts a browser, auths via session cookie, snaps, exits."""
    entry = load_alias(args.alias)
    host, session_id = http_authenticate(entry)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        ctx = browser.new_context(viewport={"width": args.width, "height": args.height})
        ctx.add_cookies([{"name": "session_id", "value": session_id,
                          "domain": host, "path": "/", "httpOnly": True, "secure": True}])
        page = ctx.new_page()
        url = args.url
        if not url.startswith("http"):
            url = entry["url"].rstrip("/") + url
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        if args.wait_selector:
            page.wait_for_selector(args.wait_selector, timeout=15_000)
        page.screenshot(path=args.to, full_page=args.full_page)
        browser.close()
    print(f"saved {args.to}")


# ---------------- parser ----------------

def build_parser():
    p = argparse.ArgumentParser(prog="odoo_playwright",
                                description="Persistent Playwright session for Odoo UI tests")
    p.add_argument("--alias", "-a")
    p.add_argument("--pretty", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sv = sub.add_parser("serve", help="Start daemon (keeps browser open, listens on unix socket)")
    sv.add_argument("--headed", action="store_true", help="Show the browser window (needs $DISPLAY)")
    sv.add_argument("--url", help="Initial path or full URL after login (default: /odoo)")
    sv.add_argument("--width", type=int, default=1366)
    sv.add_argument("--height", type=int, default=768)
    sv.add_argument("--lang", help="Locale, e.g. ar_001")
    sv.add_argument("--slow-mo", type=int, default=150,
                    help="ms between actions for human-like pacing (default 150, 0 to disable)")
    sv.set_defaults(func=cmd_serve)

    sd = sub.add_parser("send", help="Send one JSON command (or a script of commands) to the daemon")
    sd.add_argument("cmd", nargs="?", help="JSON command, e.g. '{\"op\":\"html\",\"selector\":\".o_statusbar_status\"}'")
    sd.add_argument("--script", help="File with one JSON command per line (comments start with #)")
    sd.add_argument("--timeout", type=int, default=60)
    sd.set_defaults(func=cmd_send)

    st = sub.add_parser("stop", help="Stop the daemon")
    st.set_defaults(func=cmd_stop)

    stt = sub.add_parser("status", help="Report daemon status")
    stt.set_defaults(func=cmd_status)

    sc = sub.add_parser("screenshot", help="One-shot screenshot (no daemon)")
    sc.add_argument("--url", required=True)
    sc.add_argument("--to", required=True)
    sc.add_argument("--full-page", action="store_true")
    sc.add_argument("--wait-selector")
    sc.add_argument("--width", type=int, default=1366)
    sc.add_argument("--height", type=int, default=768)
    sc.add_argument("--headed", action="store_true")
    sc.set_defaults(func=cmd_screenshot_oneshot)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
