#!/usr/bin/env python3
"""Odoo XML-RPC CLI.

Store named connections (alias) and run read/write operations against any Odoo
instance (v13+). Credentials saved under ~/.odoo_rpc/config.json (chmod 600).

Usage examples:
    odoo_rpc.py config add prod --url https://x.y --db mydb --login a@b.com --password 'xx'
    odoo_rpc.py --alias prod search_read res.partner --domain '[["is_company","=",true]]' --fields name,email --limit 5
    odoo_rpc.py --alias prod call res.partner read '[[1,2]]' '{"fields":["name"]}'
    odoo_rpc.py --alias prod fields_get res.partner --attributes string,type,required
"""
from __future__ import annotations

import argparse
import ast
import getpass
import json
import os
import ssl
import sys
import xmlrpc.client
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(os.environ.get("ODOO_RPC_HOME", str(Path.home() / ".odoo_rpc")))
CONFIG_FILE = CONFIG_DIR / "config.json"


def _load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {"aliases": {}, "default": None}
    with CONFIG_FILE.open() as f:
        return json.load(f)


def _save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG_FILE)
    os.chmod(CONFIG_FILE, 0o600)


def _resolve_alias(name: str | None) -> dict:
    cfg = _load_config()
    if not name:
        name = os.environ.get("ODOO_RPC_ALIAS") or cfg.get("default")
    if not name:
        raise SystemExit("No alias given. Use --alias NAME or set a default via `config set-default`.")
    aliases = cfg.get("aliases", {})
    if name not in aliases:
        raise SystemExit(f"Unknown alias: {name}. Known: {sorted(aliases)}")
    return aliases[name]


def _get_proxies(entry: dict) -> tuple[xmlrpc.client.ServerProxy, xmlrpc.client.ServerProxy, int, str, str, str]:
    url = entry["url"].rstrip("/")
    db = entry["db"]
    login = entry["login"]
    password = entry["password"]
    ctx = ssl._create_unverified_context() if entry.get("insecure") else None
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", context=ctx, allow_none=True)
    uid = common.authenticate(db, login, password, {})
    if not uid:
        raise SystemExit("Authentication failed.")
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", context=ctx, allow_none=True)
    return common, models, uid, db, login, password


def _parse_arg(raw: str) -> Any:
    """Parse CLI arg as JSON then fall back to Python literal."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        try:
            return ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return raw


def _dump(data: Any, pretty: bool) -> None:
    if pretty:
        print(json.dumps(data, indent=2, default=str, ensure_ascii=False))
    else:
        print(json.dumps(data, default=str, ensure_ascii=False))


# ---------- commands ----------

def cmd_config_add(args):
    cfg = _load_config()
    password = args.password or getpass.getpass("Password: ")
    cfg.setdefault("aliases", {})[args.name] = {
        "url": args.url,
        "db": args.db,
        "login": args.login,
        "password": password,
        "insecure": args.insecure,
    }
    if args.set_default or not cfg.get("default"):
        cfg["default"] = args.name
    _save_config(cfg)
    print(f"Saved alias '{args.name}'" + (" (default)" if cfg["default"] == args.name else ""))


def cmd_config_rm(args):
    cfg = _load_config()
    if args.name not in cfg.get("aliases", {}):
        raise SystemExit(f"Unknown alias: {args.name}")
    del cfg["aliases"][args.name]
    if cfg.get("default") == args.name:
        cfg["default"] = next(iter(cfg["aliases"]), None)
    _save_config(cfg)
    print(f"Removed alias '{args.name}'")


def cmd_config_list(args):
    cfg = _load_config()
    default = cfg.get("default")
    for name, entry in sorted(cfg.get("aliases", {}).items()):
        mark = "*" if name == default else " "
        print(f"{mark} {name:<20} {entry['url']}  db={entry['db']}  login={entry['login']}")


def cmd_config_set_default(args):
    cfg = _load_config()
    if args.name not in cfg.get("aliases", {}):
        raise SystemExit(f"Unknown alias: {args.name}")
    cfg["default"] = args.name
    _save_config(cfg)
    print(f"Default alias set to '{args.name}'")


def cmd_check(args):
    entry = _resolve_alias(args.alias)
    _, models, uid, db, login, password = _get_proxies(entry)
    version = xmlrpc.client.ServerProxy(f"{entry['url'].rstrip('/')}/xmlrpc/2/common", allow_none=True).version()
    print(f"OK  uid={uid}  db={db}  login={login}")
    print(f"Server version: {version.get('server_version')} ({version.get('server_version_info')})")


def _execute_kw(entry, model, method, args_list, kwargs):
    _, models, uid, db, _, password = _get_proxies(entry)
    return models.execute_kw(db, uid, password, model, method, args_list or [], kwargs or {})


def cmd_search(args):
    entry = _resolve_alias(args.alias)
    domain = _parse_arg(args.domain) if args.domain else []
    kwargs = {}
    if args.limit is not None:
        kwargs["limit"] = args.limit
    if args.offset:
        kwargs["offset"] = args.offset
    if args.order:
        kwargs["order"] = args.order
    _dump(_execute_kw(entry, args.model, "search", [domain], kwargs), args.pretty)


def cmd_search_count(args):
    entry = _resolve_alias(args.alias)
    domain = _parse_arg(args.domain) if args.domain else []
    _dump(_execute_kw(entry, args.model, "search_count", [domain], {}), args.pretty)


def cmd_read(args):
    entry = _resolve_alias(args.alias)
    ids = _parse_arg(args.ids)
    if not isinstance(ids, list):
        ids = [ids]
    kwargs = {}
    if args.fields:
        kwargs["fields"] = [s.strip() for s in args.fields.split(",") if s.strip()]
    _dump(_execute_kw(entry, args.model, "read", [ids], kwargs), args.pretty)


def cmd_search_read(args):
    entry = _resolve_alias(args.alias)
    domain = _parse_arg(args.domain) if args.domain else []
    kwargs = {}
    if args.fields:
        kwargs["fields"] = [s.strip() for s in args.fields.split(",") if s.strip()]
    if args.limit is not None:
        kwargs["limit"] = args.limit
    if args.offset:
        kwargs["offset"] = args.offset
    if args.order:
        kwargs["order"] = args.order
    _dump(_execute_kw(entry, args.model, "search_read", [domain], kwargs), args.pretty)


def cmd_create(args):
    entry = _resolve_alias(args.alias)
    vals = _parse_arg(args.values)
    _dump(_execute_kw(entry, args.model, "create", [vals], {}), args.pretty)


def cmd_write(args):
    entry = _resolve_alias(args.alias)
    ids = _parse_arg(args.ids)
    if not isinstance(ids, list):
        ids = [ids]
    vals = _parse_arg(args.values)
    _dump(_execute_kw(entry, args.model, "write", [ids, vals], {}), args.pretty)


def cmd_unlink(args):
    entry = _resolve_alias(args.alias)
    ids = _parse_arg(args.ids)
    if not isinstance(ids, list):
        ids = [ids]
    _dump(_execute_kw(entry, args.model, "unlink", [ids], {}), args.pretty)


def cmd_fields_get(args):
    entry = _resolve_alias(args.alias)
    kwargs = {}
    if args.attributes:
        kwargs["attributes"] = [s.strip() for s in args.attributes.split(",") if s.strip()]
    pos = [[]]
    _dump(_execute_kw(entry, args.model, "fields_get", pos, kwargs), args.pretty)


def cmd_call(args):
    """Generic execute_kw. Positional args and kwargs parsed from JSON/python literal strings."""
    entry = _resolve_alias(args.alias)
    pos = _parse_arg(args.args) if args.args else []
    kw = _parse_arg(args.kwargs) if args.kwargs else {}
    if not isinstance(pos, list):
        raise SystemExit("--args must be a JSON list")
    if not isinstance(kw, dict):
        raise SystemExit("--kwargs must be a JSON object")
    _dump(_execute_kw(entry, args.model, args.method, pos, kw), args.pretty)


def cmd_models(args):
    entry = _resolve_alias(args.alias)
    kwargs = {"fields": ["model", "name"], "order": "model"}
    domain = []
    if args.like:
        domain = [["model", "ilike", args.like]]
    _dump(_execute_kw(entry, "ir.model", "search_read", [domain], kwargs), args.pretty)


# ---------- UI / view helpers ----------

def _get_view(entry, model, view_type, view_id=None, context=None):
    """Try modern get_view first (Odoo 17+), fall back to fields_view_get."""
    ctx = context or {}
    try:
        kw = {"views": [[view_id, view_type]], "options": {"toolbar": True, "load_filters": True, "action_id": False}}
        if ctx:
            kw["context"] = ctx
        res = _execute_kw(entry, model, "get_views", [], kw)
        view = res["views"][view_type]
        return {
            "arch": view.get("arch"),
            "model": view.get("model") or model,
            "id": view.get("id") or view_id,
            "models": res.get("models"),
            "fields": view.get("fields"),
            "toolbar": view.get("toolbar"),
            "mode": "get_views",
        }
    except xmlrpc.client.Fault:
        pass
    try:
        kw = {"view_id": view_id, "view_type": view_type, "toolbar": True}
        if ctx:
            kw["context"] = ctx
        res = _execute_kw(entry, model, "fields_view_get", [], kw)
        return {
            "arch": res.get("arch"),
            "model": res.get("model") or model,
            "id": res.get("view_id") or view_id,
            "fields": res.get("fields"),
            "toolbar": res.get("toolbar"),
            "mode": "fields_view_get",
        }
    except xmlrpc.client.Fault as e:
        raise SystemExit(f"Failed to load view: {e.faultString}")


def cmd_view(args):
    entry = _resolve_alias(args.alias)
    ctx = _parse_arg(args.context) if args.context else {}
    view_id = None
    if args.view_id:
        view_id = int(args.view_id)
    elif args.xmlid:
        rec = _execute_kw(entry, "ir.model.data", "check_object_reference",
                          args.xmlid.split(".", 1), {})
        view_id = rec[1]
    data = _get_view(entry, args.model, args.view_type, view_id=view_id, context=ctx)
    if args.arch_only:
        print(data.get("arch") or "")
    else:
        _dump(data, args.pretty)


def cmd_view_fields(args):
    """Return the fields that appear in a view, with their declared attributes
    (invisible / readonly / required expressions, widget, modifiers). Useful to
    plan a UI-level test or scripted interaction."""
    entry = _resolve_alias(args.alias)
    ctx = _parse_arg(args.context) if args.context else {}
    view_id = int(args.view_id) if args.view_id else None
    data = _get_view(entry, args.model, args.view_type, view_id=view_id, context=ctx)
    arch = data.get("arch") or ""
    try:
        from xml.etree import ElementTree as ET
        root = ET.fromstring(arch)
    except Exception as e:
        raise SystemExit(f"Could not parse view arch: {e}")

    fields_decl = data.get("fields") or {}
    out_fields = []
    for node in root.iter("field"):
        name = node.attrib.get("name")
        if not name:
            continue
        info = {"name": name}
        for a in ("widget", "invisible", "readonly", "required", "domain",
                  "context", "options", "modifiers", "attrs", "string",
                  "optional", "nolabel", "force_save"):
            if a in node.attrib:
                info[a] = node.attrib[a]
        meta = fields_decl.get(name)
        if meta:
            info["type"] = meta.get("type")
            if meta.get("relation"):
                info["relation"] = meta["relation"]
            if meta.get("selection"):
                info["selection"] = meta["selection"]
            if meta.get("required"):
                info["required_server"] = True
        out_fields.append(info)

    buttons = []
    for node in root.iter("button"):
        b = {k: node.attrib.get(k) for k in ("name", "type", "string", "class",
                                             "confirm", "invisible", "modifiers",
                                             "attrs", "context", "states", "icon")
             if node.attrib.get(k)}
        if b:
            buttons.append(b)

    _dump({
        "model": data.get("model"),
        "view_id": data.get("id"),
        "view_type": args.view_type,
        "fields": out_fields,
        "buttons": buttons,
    }, args.pretty)


def cmd_button(args):
    """Click a view button: executes model.method(ids) with user context.
    Equivalent to pressing the button in the web client. For type='action'
    buttons use `action` subcommand instead (resolves the action record)."""
    entry = _resolve_alias(args.alias)
    ids = _parse_arg(args.ids)
    if not isinstance(ids, list):
        ids = [ids]
    ctx = _parse_arg(args.context) if args.context else {}
    kwargs = {}
    if ctx:
        kwargs["context"] = ctx
    _dump(_execute_kw(entry, args.model, args.method, [ids], kwargs), args.pretty)


def cmd_action(args):
    """Resolve an ir.actions.* record by xmlid (module.name) or id and read it."""
    entry = _resolve_alias(args.alias)
    if args.xmlid:
        ref = _execute_kw(entry, "ir.model.data", "check_object_reference",
                          args.xmlid.split(".", 1), {})
        model = ref[0]
        rec_id = ref[1]
    else:
        model = args.model or "ir.actions.act_window"
        rec_id = int(args.id)
    _dump(_execute_kw(entry, model, "read", [[rec_id]], {}), args.pretty)


def cmd_onchange(args):
    """Simulate a form onchange. values = current values dict, field_name =
    field whose onchange is being triggered, field_spec from view."""
    entry = _resolve_alias(args.alias)
    values = _parse_arg(args.values) if args.values else {}
    field_name = args.field or ""
    spec = _parse_arg(args.spec) if args.spec else {}
    ctx = _parse_arg(args.context) if args.context else {}
    kwargs = {"context": ctx} if ctx else {}
    _dump(_execute_kw(entry, args.model, "onchange",
                      [[], values, field_name, spec], kwargs), args.pretty)


def cmd_default_get(args):
    entry = _resolve_alias(args.alias)
    field_names = [s.strip() for s in args.fields.split(",") if s.strip()] if args.fields else []
    ctx = _parse_arg(args.context) if args.context else {}
    kwargs = {"context": ctx} if ctx else {}
    _dump(_execute_kw(entry, args.model, "default_get", [field_names], kwargs), args.pretty)


def cmd_name_search(args):
    entry = _resolve_alias(args.alias)
    kwargs = {}
    if args.name:
        kwargs["name"] = args.name
    if args.limit:
        kwargs["limit"] = args.limit
    if args.operator:
        kwargs["operator"] = args.operator
    if args.args_domain:
        kwargs["args"] = _parse_arg(args.args_domain)
    ctx = _parse_arg(args.context) if args.context else {}
    if ctx:
        kwargs["context"] = ctx
    _dump(_execute_kw(entry, args.model, "name_search", [], kwargs), args.pretty)


def cmd_menus(args):
    """Load user-visible menus. Falls back from load_web_menus (16+) to
    searching ir.ui.menu directly."""
    entry = _resolve_alias(args.alias)
    try:
        _dump(_execute_kw(entry, "ir.ui.menu", "load_web_menus", [False], {}), args.pretty)
        return
    except xmlrpc.client.Fault:
        pass
    try:
        _dump(_execute_kw(entry, "ir.ui.menu", "load_menus", [False], {}), args.pretty)
        return
    except xmlrpc.client.Fault:
        pass
    domain = []
    if args.like:
        domain = [["name", "ilike", args.like]]
    _dump(_execute_kw(entry, "ir.ui.menu", "search_read",
                      [domain], {"fields": ["id", "name", "parent_id", "action", "sequence"],
                                 "order": "sequence,id"}), args.pretty)


def cmd_access(args):
    """Report access rights for user on a model: read/write/create/unlink."""
    entry = _resolve_alias(args.alias)
    out = {}
    for op in ("read", "write", "create", "unlink"):
        try:
            out[op] = _execute_kw(entry, args.model, "check_access_rights", [op], {"raise_exception": False})
        except xmlrpc.client.Fault as e:
            out[op] = f"fault: {e.faultString}"
    _dump(out, args.pretty)


def cmd_xmlid(args):
    """Resolve an xmlid 'module.name' to (model, id). Useful to find view ids,
    action ids, specific demo records."""
    entry = _resolve_alias(args.alias)
    module, name = args.xmlid.split(".", 1)
    try:
        res = _execute_kw(entry, "ir.model.data", "check_object_reference", [module, name], {})
        _dump({"xmlid": args.xmlid, "model": res[0], "id": res[1]}, args.pretty)
    except xmlrpc.client.Fault as e:
        raise SystemExit(f"xmlid not found: {e.faultString}")


# ---------- investigation / power helpers ----------

def cmd_db_list(args):
    """Discover databases on an Odoo host via /web/database/list."""
    import urllib.request
    url = args.url.rstrip("/") + "/web/database/list"
    req = urllib.request.Request(
        url, method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"jsonrpc": "2.0", "method": "call", "params": {}}).encode(),
    )
    ctx = ssl._create_unverified_context() if args.insecure else None
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        payload = json.loads(resp.read().decode())
    _dump(payload.get("result", payload), args.pretty)


def cmd_fields(args):
    """Compact field list: name, type, relation, required, string. Supports --like."""
    entry = _resolve_alias(args.alias)
    kw = {"attributes": ["string", "type", "required", "relation", "selection", "store", "readonly", "help"]}
    data = _execute_kw(entry, args.model, "fields_get", [[]], kw)
    rows = []
    for name, meta in sorted(data.items()):
        if args.like and args.like.lower() not in name.lower() and args.like.lower() not in (meta.get("string") or "").lower():
            continue
        rows.append({
            "name": name,
            "type": meta.get("type"),
            "string": meta.get("string"),
            "relation": meta.get("relation"),
            "required": bool(meta.get("required")),
            "readonly": bool(meta.get("readonly")),
            "store": meta.get("store", True),
            "selection": meta.get("selection"),
            "help": meta.get("help"),
        })
    _dump(rows, args.pretty)


def cmd_trace(args):
    """Audit trail for a record: chatter + tracking values + nearby module upgrades.
    Great for 'why did this record change?' investigations."""
    entry = _resolve_alias(args.alias)
    rec_id = int(args.id)
    rec = _execute_kw(entry, args.model, "read", [[rec_id]],
                      {"fields": ["display_name", "write_uid", "write_date", "create_uid", "create_date"]})
    if not rec:
        raise SystemExit(f"{args.model} {rec_id} not found or not accessible")
    rec = rec[0]
    msgs = _execute_kw(entry, "mail.message", "search_read",
                       [[["model", "=", args.model], ["res_id", "=", rec_id]]],
                       {"fields": ["id", "date", "author_id", "subject", "body", "subtype_id", "tracking_value_ids", "message_type"],
                        "order": "date desc", "limit": args.limit})
    track_ids = sorted({tid for m in msgs for tid in (m.get("tracking_value_ids") or [])})
    tracks = _execute_kw(entry, "mail.tracking.value", "read", [track_ids],
                         {"fields": ["id", "field_id", "display_name", "mail_message_id",
                                     "old_value_char", "new_value_char",
                                     "old_value_float", "new_value_float",
                                     "old_value_integer", "new_value_integer",
                                     "old_value_text", "new_value_text",
                                     "old_value_datetime", "new_value_datetime"]}) if track_ids else []
    track_by_msg = {}
    for t in tracks:
        mid = t["mail_message_id"][0] if t.get("mail_message_id") else None
        track_by_msg.setdefault(mid, []).append(t)
    for m in msgs:
        m["_tracking"] = track_by_msg.get(m["id"], [])

    nearby_modules = []
    wd = rec.get("write_date")
    if wd:
        before = f"{wd[:19]}"
        nearby_modules = _execute_kw(entry, "ir.module.module", "search_read",
                                     [[["state", "=", "installed"],
                                       ["write_date", ">=", f"{wd[:10]} 00:00:00"],
                                       ["write_date", "<=", before]]],
                                     {"fields": ["name", "display_name", "write_date", "write_uid", "latest_version"],
                                      "order": "write_date desc", "limit": 50})

    _dump({
        "record": rec,
        "messages": msgs,
        "nearby_module_upgrades": nearby_modules,
    }, args.pretty)


def cmd_diff(args):
    """Field-by-field diff of two records of same model. Useful for 'why does X differ from Y'."""
    entry = _resolve_alias(args.alias)
    ids = [int(args.id1), int(args.id2)]
    kw = {}
    if args.fields:
        kw["fields"] = [s.strip() for s in args.fields.split(",") if s.strip()]
    recs = _execute_kw(entry, args.model, "read", [ids], kw)
    if len(recs) != 2:
        raise SystemExit(f"Expected 2 records, got {len(recs)}")
    a = {k: v for k, v in recs[0].items() if k != "id"}
    b = {k: v for k, v in recs[1].items() if k != "id"}
    diff = []
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            diff.append({"field": k, f"id_{ids[0]}": a.get(k), f"id_{ids[1]}": b.get(k)})
    _dump({"model": args.model, "ids": ids, "diff": diff, "same_count": len(a) - len(diff)}, args.pretty)


def cmd_refs(args):
    """Find every M2O field that references this record. Walks ir.model.fields."""
    entry = _resolve_alias(args.alias)
    rec_id = int(args.id)
    m2o_fields = _execute_kw(entry, "ir.model.fields", "search_read",
                             [[["ttype", "=", "many2one"], ["relation", "=", args.model], ["store", "=", True]]],
                             {"fields": ["name", "model", "field_description"]})
    out = []
    for f in m2o_fields:
        try:
            cnt = _execute_kw(entry, f["model"], "search_count", [[[f["name"], "=", rec_id]]], {})
        except xmlrpc.client.Fault:
            continue
        if cnt:
            sample = _execute_kw(entry, f["model"], "search_read",
                                 [[[f["name"], "=", rec_id]]],
                                 {"fields": ["id", "display_name"], "limit": args.sample})
            out.append({"model": f["model"], "field": f["name"], "label": f["field_description"],
                        "count": cnt, "sample": sample})
    _dump({"target": {"model": args.model, "id": rec_id}, "referenced_by": out}, args.pretty)


def cmd_snapshot(args):
    """Snapshot records to a local JSON file. Pair with `restore`.

    By default reads all stored, non-computed fields so restore can round-trip."""
    entry = _resolve_alias(args.alias)
    ids = _parse_arg(args.ids)
    if not isinstance(ids, list):
        ids = [ids]
    if args.fields:
        fields = [s.strip() for s in args.fields.split(",") if s.strip()]
    else:
        fg = _execute_kw(entry, args.model, "fields_get", [[]],
                         {"attributes": ["store", "readonly", "type", "related"]})
        fields = [n for n, m in fg.items()
                  if m.get("store") and not m.get("related") and m.get("type") not in ("binary", "one2many")]
    recs = _execute_kw(entry, args.model, "read", [ids], {"fields": fields})
    import datetime
    out = {"alias": entry.get("url"), "db": entry.get("db"), "model": args.model,
           "fields": fields, "records": recs,
           "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    Path(args.to).write_text(json.dumps(out, indent=2, default=str, ensure_ascii=False))
    print(f"Wrote {len(recs)} records to {args.to}")


def cmd_restore(args):
    """Restore from a snapshot file. Overwrites field values on existing records."""
    entry = _resolve_alias(args.alias)
    snap = json.loads(Path(args.from_).read_text())
    model = args.model or snap["model"]
    skip = set(args.skip.split(",")) if args.skip else set()
    skip |= {"id", "display_name", "create_date", "create_uid", "write_date", "write_uid", "__last_update"}
    n = 0
    for rec in snap["records"]:
        vals = {}
        for k, v in rec.items():
            if k in skip:
                continue
            # Many2one tuples -> id
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], int):
                v = v[0]
            vals[k] = v
        if not vals:
            continue
        _execute_kw(entry, model, "write", [[rec["id"]], vals], {})
        n += 1
    print(f"Restored {n} records from {args.from_} into {model}")


def cmd_view_chain(args):
    """List the view inheritance chain for a model+view_type.
    Shows every ir.ui.view with module, priority, inherit parent."""
    entry = _resolve_alias(args.alias)
    data = _get_view(entry, args.model, args.view_type)
    base_id = data.get("id")
    views = _execute_kw(
        entry, "ir.ui.view", "search_read",
        [[["model", "=", args.model], ["type", "=", args.view_type]]],
        {"fields": ["id", "name", "key", "priority", "inherit_id", "mode", "active"],
         "order": "priority,id"},
    )
    _dump({"model": args.model, "view_type": args.view_type, "base_view_id": base_id, "views": views}, args.pretty)


def cmd_report(args):
    """Render a QWeb report to PDF via /report/pdf/<xmlid>/<ids>. Saves to --save."""
    import urllib.request
    entry = _resolve_alias(args.alias)
    # Authenticate via /web/session/authenticate to get a session cookie
    url = entry["url"].rstrip("/")
    ctx = ssl._create_unverified_context() if entry.get("insecure") else None
    auth_payload = json.dumps({"jsonrpc": "2.0", "params": {
        "db": entry["db"], "login": entry["login"], "password": entry["password"]}}).encode()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    req = urllib.request.Request(f"{url}/web/session/authenticate", data=auth_payload,
                                 headers={"Content-Type": "application/json"})
    opener.open(req, context=ctx, timeout=30).read()
    ids_str = args.ids if "," in args.ids else args.ids
    pdf_url = f"{url}/report/pdf/{args.xmlid}/{ids_str}"
    data = opener.open(pdf_url, context=ctx, timeout=120).read()
    Path(args.save).write_bytes(data)
    print(f"Wrote {len(data)} bytes to {args.save}")


def cmd_rules(args):
    """List ir.rule record rules affecting a model for current user."""
    entry = _resolve_alias(args.alias)
    rules = _execute_kw(entry, "ir.rule", "search_read",
                       [[["model_id.model", "=", args.model], ["active", "=", True]]],
                       {"fields": ["id", "name", "domain_force", "groups", "perm_read", "perm_write", "perm_create", "perm_unlink", "global"],
                        "order": "id"})
    _dump(rules, args.pretty)


def cmd_upgrade(args):
    """Trigger button_immediate_upgrade on one or more modules by name."""
    entry = _resolve_alias(args.alias)
    names = [s.strip() for s in args.names.split(",") if s.strip()]
    mids = _execute_kw(entry, "ir.module.module", "search", [[["name", "in", names]]], {})
    if not mids:
        raise SystemExit(f"No installed module matches: {names}")
    if not args.yes:
        raise SystemExit(f"Would upgrade {len(mids)} modules {names}. Pass --yes to proceed.")
    _execute_kw(entry, "ir.module.module", "button_immediate_upgrade", [mids], {})
    print(f"Upgrade triggered for {names}")


def cmd_install(args):
    """Install (or upgrade) one or more modules by name."""
    entry = _resolve_alias(args.alias)
    names = [s.strip() for s in args.names.split(",") if s.strip()]
    mids = _execute_kw(entry, "ir.module.module", "search", [[["name", "in", names]]], {})
    if not mids:
        raise SystemExit(f"No module matches: {names}")
    if not args.yes:
        raise SystemExit(f"Would install {len(mids)} modules {names}. Pass --yes to proceed.")
    _execute_kw(entry, "ir.module.module", "button_immediate_install", [mids], {})
    print(f"Install triggered for {names}")


def cmd_doctor(args):
    """Environment status check. Emits JSON describing what is set up and what is missing.
    The skill's SKILL.md tells the AI to run this first and ask the user to fix gaps."""
    import shutil as _shutil
    out = {"ok": True, "issues": [], "info": {}}

    # Python
    out["info"]["python"] = sys.version.split()[0]

    # Config file
    cfg_path = CONFIG_FILE
    out["info"]["config_file"] = str(cfg_path)
    if not cfg_path.exists():
        out["ok"] = False
        out["issues"].append({"id": "no_config", "severity": "error",
                              "message": "No ~/.odoo_rpc/config.json yet. No connection aliases configured.",
                              "fix": "python3 /opt/odoo_rpc.py config add <alias> --url ... --db ... --login ... --password ..."})
    else:
        try:
            cfg = _load_config()
            aliases = cfg.get("aliases", {})
            default = cfg.get("default")
            out["info"]["aliases"] = sorted(aliases.keys())
            out["info"]["default_alias"] = default
            if not aliases:
                out["ok"] = False
                out["issues"].append({"id": "no_aliases", "severity": "error",
                                      "message": "Config file exists but has no aliases.",
                                      "fix": "python3 /opt/odoo_rpc.py config add <alias> ..."})
            # Try the default alias
            if default and args.check_connectivity:
                try:
                    entry = aliases[default]
                    _get_proxies(entry)
                    out["info"]["default_reachable"] = True
                except Exception as e:
                    out["ok"] = False
                    out["issues"].append({"id": "default_unreachable", "severity": "warning",
                                          "message": f"Default alias '{default}' failed: {e}",
                                          "fix": f"python3 /opt/odoo_rpc.py -a {default} check"})
        except Exception as e:
            out["ok"] = False
            out["issues"].append({"id": "config_unreadable", "severity": "error",
                                  "message": f"Config file unreadable: {e}",
                                  "fix": f"inspect {cfg_path} manually"})

    # Playwright
    venv = Path(os.environ.get("HOME", "/root")) / ".odoo_rpc" / "venv"
    pw_py = venv / "bin" / "python"
    out["info"]["playwright_venv"] = str(venv)
    if pw_py.exists():
        import subprocess
        try:
            r = subprocess.run([str(pw_py), "-c", "import playwright; print(playwright.__version__)"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                out["info"]["playwright_version"] = r.stdout.strip()
                # Check Chromium
                r2 = subprocess.run([str(pw_py), "-c",
                                     "from playwright.sync_api import sync_playwright\n"
                                     "with sync_playwright() as p:\n"
                                     "    print(p.chromium.executable_path)"],
                                    capture_output=True, text=True, timeout=15)
                if r2.returncode == 0 and _shutil.which(r2.stdout.strip()) or Path(r2.stdout.strip()).exists():
                    out["info"]["chromium"] = r2.stdout.strip()
                else:
                    out["issues"].append({"id": "no_chromium", "severity": "warning",
                                          "message": "Playwright installed but Chromium missing.",
                                          "fix": f"{pw_py} -m playwright install chromium"})
            else:
                out["issues"].append({"id": "playwright_broken", "severity": "warning",
                                      "message": "Playwright venv exists but import fails.",
                                      "fix": "bash /opt/odoo-rpc/scripts/install_playwright.sh"})
        except Exception as e:
            out["issues"].append({"id": "playwright_check_failed", "severity": "warning",
                                  "message": f"Playwright check failed: {e}",
                                  "fix": "bash /opt/odoo-rpc/scripts/install_playwright.sh"})
    else:
        out["issues"].append({"id": "no_playwright", "severity": "info",
                              "message": "Playwright not installed. UI tests unavailable.",
                              "fix": "bash /opt/odoo-rpc/scripts/install_playwright.sh"})

    # Skill content location
    for loc in ("/opt/odoo-rpc", str(Path.home() / ".claude/skills/odoo-rpc")):
        if Path(loc).is_dir():
            out["info"].setdefault("skill_locations", []).append(loc)

    _dump(out, args.pretty)


# ---------- parser ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="odoo_rpc", description="Odoo XML-RPC CLI")
    p.add_argument("--alias", "-a", help="Named connection (see `config list`). Defaults to env ODOO_RPC_ALIAS or configured default.")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")

    sub = p.add_subparsers(dest="cmd", required=True)

    cfg = sub.add_parser("config", help="Manage connection aliases")
    cfg_sub = cfg.add_subparsers(dest="action", required=True)

    c_add = cfg_sub.add_parser("add", help="Add or overwrite an alias")
    c_add.add_argument("name")
    c_add.add_argument("--url", required=True)
    c_add.add_argument("--db", required=True)
    c_add.add_argument("--login", required=True)
    c_add.add_argument("--password", help="Password (if omitted, prompts)")
    c_add.add_argument("--insecure", action="store_true", help="Skip TLS verification")
    c_add.add_argument("--set-default", action="store_true")
    c_add.set_defaults(func=cmd_config_add)

    c_rm = cfg_sub.add_parser("rm", help="Remove an alias")
    c_rm.add_argument("name")
    c_rm.set_defaults(func=cmd_config_rm)

    c_ls = cfg_sub.add_parser("list", help="List aliases")
    c_ls.set_defaults(func=cmd_config_list)

    c_sd = cfg_sub.add_parser("set-default", help="Set default alias")
    c_sd.add_argument("name")
    c_sd.set_defaults(func=cmd_config_set_default)

    chk = sub.add_parser("check", help="Authenticate and print server version")
    chk.set_defaults(func=cmd_check)

    s = sub.add_parser("search", help="search(model, domain) -> [ids]")
    s.add_argument("model"); s.add_argument("--domain", default="[]"); s.add_argument("--limit", type=int); s.add_argument("--offset", type=int, default=0); s.add_argument("--order")
    s.set_defaults(func=cmd_search)

    sc = sub.add_parser("search_count", help="search_count(model, domain)")
    sc.add_argument("model"); sc.add_argument("--domain", default="[]")
    sc.set_defaults(func=cmd_search_count)

    r = sub.add_parser("read", help="read(model, ids, fields)")
    r.add_argument("model"); r.add_argument("ids", help="JSON list or single int"); r.add_argument("--fields", help="comma-separated")
    r.set_defaults(func=cmd_read)

    sr = sub.add_parser("search_read", help="search_read(model, domain, fields)")
    sr.add_argument("model"); sr.add_argument("--domain", default="[]"); sr.add_argument("--fields"); sr.add_argument("--limit", type=int); sr.add_argument("--offset", type=int, default=0); sr.add_argument("--order")
    sr.set_defaults(func=cmd_search_read)

    cr = sub.add_parser("create", help="create(model, values)")
    cr.add_argument("model"); cr.add_argument("values", help="JSON dict")
    cr.set_defaults(func=cmd_create)

    w = sub.add_parser("write", help="write(model, ids, values)")
    w.add_argument("model"); w.add_argument("ids"); w.add_argument("values")
    w.set_defaults(func=cmd_write)

    u = sub.add_parser("unlink", help="unlink(model, ids)")
    u.add_argument("model"); u.add_argument("ids")
    u.set_defaults(func=cmd_unlink)

    fg = sub.add_parser("fields_get", help="fields_get(model, attributes)")
    fg.add_argument("model"); fg.add_argument("--attributes", help="comma-separated, e.g. string,type,required,help")
    fg.set_defaults(func=cmd_fields_get)

    call = sub.add_parser("call", help="Generic execute_kw: model method --args '[[1]]' --kwargs '{...}'")
    call.add_argument("model"); call.add_argument("method"); call.add_argument("--args", default="[]"); call.add_argument("--kwargs", default="{}")
    call.set_defaults(func=cmd_call)

    m = sub.add_parser("models", help="List installed models (ir.model)")
    m.add_argument("--like", help="ilike filter on model name")
    m.set_defaults(func=cmd_models)

    # ---- UI / view ----
    v = sub.add_parser("view", help="Load a view's arch + fields (get_views / fields_view_get)")
    v.add_argument("model")
    v.add_argument("--view-type", default="form", choices=["form", "list", "tree", "kanban", "search", "calendar", "pivot", "graph", "activity", "qweb"])
    v.add_argument("--view-id", help="Specific view id (int). Else default for type.")
    v.add_argument("--xmlid", help="Resolve view id from xmlid 'module.name'")
    v.add_argument("--context", help="Context dict (JSON) — e.g. '{\"lang\":\"en_US\"}'")
    v.add_argument("--arch-only", action="store_true", help="Print only the XML arch to stdout")
    v.set_defaults(func=cmd_view)

    vf = sub.add_parser("view_fields", help="Extract fields + buttons declared in a view, with modifiers")
    vf.add_argument("model")
    vf.add_argument("--view-type", default="form")
    vf.add_argument("--view-id")
    vf.add_argument("--context")
    vf.set_defaults(func=cmd_view_fields)

    bt = sub.add_parser("button", help="Simulate clicking a view button: model.method(ids)")
    bt.add_argument("model"); bt.add_argument("method"); bt.add_argument("ids")
    bt.add_argument("--context", help="Context dict (JSON)")
    bt.set_defaults(func=cmd_button)

    ac = sub.add_parser("action", help="Resolve an ir.actions record (by xmlid or id)")
    ac.add_argument("--xmlid"); ac.add_argument("--id"); ac.add_argument("--model", help="e.g. ir.actions.act_window (used with --id)")
    ac.set_defaults(func=cmd_action)

    on = sub.add_parser("onchange", help="Run model.onchange(values, field, spec)")
    on.add_argument("model"); on.add_argument("--values", required=True); on.add_argument("--field", default="")
    on.add_argument("--spec", default="{}"); on.add_argument("--context")
    on.set_defaults(func=cmd_onchange)

    dg = sub.add_parser("default_get", help="model.default_get([fields])")
    dg.add_argument("model"); dg.add_argument("--fields", help="comma-separated field names"); dg.add_argument("--context")
    dg.set_defaults(func=cmd_default_get)

    ns = sub.add_parser("name_search", help="model.name_search(name, args, operator, limit)")
    ns.add_argument("model"); ns.add_argument("--name", default=""); ns.add_argument("--operator", default="ilike")
    ns.add_argument("--limit", type=int); ns.add_argument("--args-domain", help="Extra domain (JSON)")
    ns.add_argument("--context")
    ns.set_defaults(func=cmd_name_search)

    mn = sub.add_parser("menus", help="Load user-visible menus (load_web_menus/load_menus/fallback)")
    mn.add_argument("--like", help="For fallback: ilike on name")
    mn.set_defaults(func=cmd_menus)

    ar = sub.add_parser("access", help="Report read/write/create/unlink access for current user")
    ar.add_argument("model")
    ar.set_defaults(func=cmd_access)

    xi = sub.add_parser("xmlid", help="Resolve 'module.name' xmlid to (model, id)")
    xi.add_argument("xmlid")
    xi.set_defaults(func=cmd_xmlid)

    # ---- investigation / power helpers ----
    dbl = sub.add_parser("db-list", help="Discover DB names on a server (/web/database/list)")
    dbl.add_argument("url", help="Base URL, e.g. https://host.odoo.com")
    dbl.add_argument("--insecure", action="store_true")
    dbl.set_defaults(func=cmd_db_list)

    fl = sub.add_parser("fields", help="Compact field list with --like filter")
    fl.add_argument("model")
    fl.add_argument("--like", help="ilike filter on name or label")
    fl.set_defaults(func=cmd_fields)

    tr = sub.add_parser("trace", help="Audit trail for a record: chatter + tracking + nearby module upgrades")
    tr.add_argument("model"); tr.add_argument("id")
    tr.add_argument("--limit", type=int, default=20, help="Max chatter messages (default 20)")
    tr.set_defaults(func=cmd_trace)

    df = sub.add_parser("diff", help="Field-by-field diff of two records of the same model")
    df.add_argument("model"); df.add_argument("id1"); df.add_argument("id2")
    df.add_argument("--fields", help="comma-separated to limit")
    df.set_defaults(func=cmd_diff)

    rf = sub.add_parser("refs", help="Find all M2O fields referencing a record (reverse FK)")
    rf.add_argument("model"); rf.add_argument("id")
    rf.add_argument("--sample", type=int, default=5, help="Sample records per referencing model (default 5)")
    rf.set_defaults(func=cmd_refs)

    sn = sub.add_parser("snapshot", help="Snapshot records to a JSON file (safety net before writes)")
    sn.add_argument("model"); sn.add_argument("ids"); sn.add_argument("--to", required=True)
    sn.add_argument("--fields", help="Limit to these fields (default: all stored, non-computed)")
    sn.set_defaults(func=cmd_snapshot)

    rs = sub.add_parser("restore", help="Restore records from a snapshot file")
    rs.add_argument("--from", required=True, dest="from_")
    rs.add_argument("--model", help="Override model (default from file)")
    rs.add_argument("--skip", help="Comma-separated fields to skip on restore")
    rs.set_defaults(func=cmd_restore)

    vc = sub.add_parser("view-chain", help="List all ir.ui.view entries for model+view_type (inheritance chain)")
    vc.add_argument("model"); vc.add_argument("--view-type", default="form")
    vc.set_defaults(func=cmd_view_chain)

    rp = sub.add_parser("report", help="Render a QWeb report to PDF via /report/pdf/<xmlid>/<ids>")
    rp.add_argument("xmlid"); rp.add_argument("ids", help="Comma-separated IDs or single int")
    rp.add_argument("--save", required=True, help="Local file path")
    rp.set_defaults(func=cmd_report)

    rl = sub.add_parser("rules", help="List active ir.rule record rules for a model")
    rl.add_argument("model")
    rl.set_defaults(func=cmd_rules)

    up = sub.add_parser("upgrade", help="Trigger button_immediate_upgrade on modules (comma-separated names)")
    up.add_argument("names"); up.add_argument("--yes", action="store_true")
    up.set_defaults(func=cmd_upgrade)

    ins = sub.add_parser("install", help="Trigger button_immediate_install on modules (comma-separated names)")
    ins.add_argument("names"); ins.add_argument("--yes", action="store_true")
    ins.set_defaults(func=cmd_install)

    dr = sub.add_parser("doctor", help="Environment status check (aliases, Playwright, Chromium, skill location)")
    dr.add_argument("--check-connectivity", action="store_true", help="Also try to auth against the default alias")
    dr.set_defaults(func=cmd_doctor)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except xmlrpc.client.Fault as e:
        print(f"XML-RPC Fault: {e.faultCode}: {e.faultString}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
