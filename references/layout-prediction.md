# Predicting layout issues from view arch

Goal: catch layout breaks before the user sees them, by reading the view arch and the fields the arch references.

Load this when:
- User asks "will this view break on upgrade"
- UI test fails on a missing selector
- A form shows wrong fields after module update
- Someone just added XPath inherit XML and you want to sanity-check

## The three families of layout breaks

### 1. Field removal / rename
A `<field name="foo"/>` where `foo` no longer exists on the model.

Detection:
```
# fetch the view
view MODEL --view-type form --arch-only > /tmp/arch.xml

# list current model fields
fields MODEL --like . > /tmp/fields.json

# any <field name="X"/> whose X is not in fields.json is a break
python3 -c "
import re, json
arch = open('/tmp/arch.xml').read()
fields = {f['name'] for f in json.load(open('/tmp/fields.json'))}
refs = set(re.findall(r'<field[^>]*name=\"([^\"]+)\"', arch))
missing = refs - fields
print('MISSING FIELDS:', sorted(missing))
"
```

In the real v18→v19 bluehills session, `hr.payslip` dropped `contract_id` and `number` — any inherited view referencing them is now a `ParseError` at load.

### 2. Attribute refactor on a container tag
Odoo tightens view engine per release. v19 refactor dropped `expand`, `string`, and `name` attributes on `<group>` nested in `<search>` views. Any view still carrying them is a hard parse error at module install.

Known-dead patterns per version:

| Dropped in | Pattern |
|--|--|
| v17 | `<attribute name="attrs">` (replaced by `invisible`/`readonly`/`required` with python expressions) |
| v17 | `<attribute name="states">` on fields and buttons |
| v18 | `<tree>` renamed `<list>` for list views (compat shim lingers; new modules should use `<list>`) |
| v19 | `<group expand="0" string="..." name="...">` inside `<search>` views |
| v19 | `<menuitem groups="base.group_user">` short form on some menus (needs full `<record>` ref) |

Detection with grep:
```
grep -rln 'group expand=.*string="Group By"' <path>
grep -rln 'attrs=' <path>/views/
grep -rln '<tree ' <path>/views/
```

### 3. Modifier expression regression
`invisible="state != 'draft'"` evaluates on the client. If a field changed from Char to Selection (or vice versa), the quoting breaks. If a referenced field was removed, the modifier silently always-evaluates-true (field is undefined).

Detection: `view_fields MODEL --view-type form` dumps every modifier expression. For each one, confirm each referenced field still exists.

```
view_fields hr.payslip --view-type form | python3 -c "
import json, re, sys
d = json.load(sys.stdin)
exprs = []
for f in d['fields']:
    for k in ('invisible','readonly','required'):
        v = f.get(k)
        if v and v not in ('1','True'):
            exprs.append((f['name'], k, v))
for b in d['buttons']:
    for k in ('invisible','readonly'):
        v = b.get(k)
        if v and v not in ('1','True'):
            exprs.append((b.get('name'), k, v))
# extract bare identifiers from expression
ids = set()
for _,_,v in exprs: ids |= set(re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', v))
# keywords to drop
kw = {'and','or','not','in','is','True','False','None','state'}
print(sorted(ids - kw))
"
```
Then compare that set to `fields MODEL --like .`.

## Walk-the-chain protocol

For any suspicious model+view_type:

```
view-chain MODEL --view-type form
```
Lists every `ir.ui.view` in priority order. Each row has:
- `name` — human label
- `key` — xmlid-style key when set
- `priority` — order (lower = applied earlier; mind merge order)
- `inherit_id` — the parent view, if any
- `mode` — `primary` (standalone) or `extension`
- `active` — if False, the view does not merge in

For each inheriting view, fetch the arch:
```
read ir.ui.view <id> --fields name,arch_updated,arch
```
`arch_updated` is the stored, patched arch; `arch` falls back to file. If `arch_updated` differs from `arch`, Studio or a user has edited the view from the web client. That's a prime suspect for regression after upgrade (studio patches don't survive XPath drift).

## Known-fragile XPaths

Inherited views that use `xpath` referring to a specific child position break when parent view adds/removes a sibling:

- `//field[@name='foo']/..` — relies on `foo` existing.
- `//page[position()=3]` — relies on exactly 3 pages.
- `//group[1]/field[@name='bar']` — breaks if the field moves to another `<group>`.

Safer patterns:
- `//field[@name='foo']` + `position="after"`.
- Named `<page name="...">` and target it by name.

When reviewing a custom module, grep for the fragile ones:
```
grep -rE 'xpath.*position=|xpath.*parent::' <path>/views/
```

## Multi-company / multi-lang gotchas

- A view with `groups="base.group_multi_company"` only renders when the user has that group; if the user complains "I don't see the Company field", check this before anything else.
- `--context '{"lang":"ar_001"}'` on `view` fetches the Arabic-translated arch (field strings, button labels). If RTL and the arch has fixed CSS classes (`col-6`, `float-end`), RTL rendering may push content off-screen — not a parse error, but a visible layout break. Use Playwright screenshots to confirm.

## When Playwright is the only answer

The arch tells you what the server sends. It does not tell you:
- How wide text renders in Arabic (critical for Saudi tenants)
- Whether a kanban card overflows at 1366×768
- Whether a sticky header overlaps the first row
- Whether a modal's save button is below the fold

Those need `scripts/odoo_playwright.py screenshot MODEL ID`. See `references/playwright.md`.
