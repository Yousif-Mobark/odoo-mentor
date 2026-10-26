# Investigation protocol — always analyze DB technical objects

Rule: **inspect before you conclude**. Every data issue, server error, stuck state, or vanishing record starts with technical inspection of the ir.* and chatter artifacts around the record. Never answer from pattern-matching alone.

## The 5-step base protocol

Apply to every issue:

### 1. Identify the record precisely
```
python3 /opt/odoo_rpc.py -a <alias> read MODEL ID --pretty
```
Full default-field read. No `--fields`. You want to see state, timestamps, M2O labels, flags, and anything else the server exposes.

Also:
```
python3 /opt/odoo_rpc.py -a <alias> fields MODEL --like <field_name_from_error>
```
Confirms the field still exists under that name on this Odoo version.

### 2. Audit who touched it, when, and from where

```
python3 /opt/odoo_rpc.py -a <alias> trace MODEL ID --pretty
```

The output has three parts:

- **record**: current `write_uid`, `write_date`, `create_uid`, `create_date`.
- **messages**: chatter in reverse chronological order; each message carries `_tracking` with field-level before/after values.
- **nearby_module_upgrades**: every `ir.module.module` with `write_date` on the same day. Catches SaaS auto-migrations.

Red flags:
- `write_uid` = `1` (OdooBot) with a `write_date` seconds after a module upgrade → migration bug.
- `write_uid` = `1` with no corresponding upgrade → cron / server action.
- `write_date` close to a client-side activity → look at the chatter message right before.
- Several records with the **exact same `write_date` to the second** → script / batch / migration (never UI-manual).

### 3. Walk the inheritance chain for the error

If the error is from a Python call:
- The traceback's **last** `File` line names the real culprit — but it's usually inside stdcore. The guilty override is often one frame up.
- The override chain for `_post` on `account.move` goes through many modules — `sale_timesheet`, `sale`, `account`, `hr_payroll_expense`, `account_loans`, `account_invoice_extract`, `account_asset`, `purchase_stock`, `l10n_sa`, `appointment_account_payment`, `account_reports`, `stock_account`, `account_edi`, `account_accountant`. Read top to bottom; the FIRST override to call `super()` and then fail inside stdcore is where to look.

If the error is from a view:
```
python3 /opt/odoo_rpc.py -a <alias> view-chain MODEL --view-type form --pretty
```
Lists every inheriting view by priority. The one in the user's custom module is a prime suspect for parse errors.

### 4. Scope the blast radius

The record you were given is rarely alone. Find siblings:

- Same batch: `search_read MODEL --domain '[["payslip_run_id","=",N]]'` for payslips.
- Same company + period: `search_count account.move --domain '[["journal_id","=",J],["date",">=","YYYY-MM-01"],["date","<=","YYYY-MM-31"]]'`.
- Same field corruption: `search_read MODEL --domain '[["bad_field","!=",false]]'` then filter the key client-side.
- Same `write_date`: `search_count MODEL --domain '[["write_date","=","YYYY-MM-DD HH:MM:SS"]]'`.

A corruption that hits one record almost always hits a cohort.

### 5. Propose fix with snapshot + rollback plan

```
python3 /opt/odoo_rpc.py -a <alias> snapshot MODEL '[list of ids]' --to /tmp/<task>-pre.json
# the proposed write(s)
# rollback: restore --from /tmp/<task>-pre.json
```

Only then execute, with explicit user "yes".

## Pattern library

Short recipes keyed by the symptom.

### "Field has wrong value — who set it?"

```
trace MODEL ID
```
Look at the latest message with `_tracking` referencing that field. If no chatter entry → not UI-manual, go to `nearby_module_upgrades`.

### "Record vanished"

Not actually gone — probably `active = False` or outside the user's record rules.

```
search_count MODEL --domain '[["id","=",N]]'                 # with company_id in context
call MODEL search --args '[[["id","=",N]],0,0,"id",false]'   # pass count=False, add context
rules MODEL                                                   # see what rules apply
```

If still 0, likely unlinked. Check:
```
search_read mail.message --domain '[["model","=","MODEL"],["res_id","=",N]]' --fields date,subject,body,subtype_id
```
Odoo logs an unlink into `mail.message` with subtype `discussion`.

### "State is X but button says it should be Y"

- `view_fields MODEL --view-type form` → read the button's `invisible` expression.
- Fetch current `state` + referenced fields from the expression.
- Compute the expression by hand.

### "Move_id False but payslip is validated"

Specifically Odoo 19 payroll. See `recipes.md` → "Regenerate payslip JE".

### "Analytic distribution JSON is wrong"

Pattern: key is a JSON-dumped dict instead of `"<id>"` or `"id,id"`.

```
search_read hr.salary.rule --domain '[["analytic_distribution","!=",false]]' --fields analytic_distribution,write_uid,write_date
```

If `write_uid=1` and `write_date` identical across all affected rows → migration script. See `recipes.md` → "Fix bad analytic_distribution".

### "Report prints wrong"

Reports are QWeb templates (`ir.ui.view` type=`qweb`). Fetch:
```
view-chain hr.payslip --view-type qweb
```
Or directly: `search_read ir.ui.view --domain '[["type","=","qweb"],["key","ilike","payslip"]]'`.

To render and inspect:
```
report hr_payroll.action_report_payslip 767 --save /tmp/slip.pdf
```

### "Can't understand the error traceback"

Save it to a file and read top-down:
1. The HTTP endpoint frame (`controllers/*.py`) — ignore, infrastructure.
2. The `execute_kw` / `call_kw` frame — ignore.
3. The MODEL.METHOD call — this is the real action.
4. Every override above the final frame — read in order to see where custom modules intercept.
5. The final frame — the actual Python exception.

Grep source for the final frame's file:line to see context:
```
sed -n 'N-5,N+5 p' /path/to/file.py   # where N is the line
```

## Technical object cheat sheet

Objects to inspect when symptom is...

| Symptom | Object |
|--|--|
| Field doesn't exist / wrong type | `ir.model.fields` |
| View won't load / parse error | `ir.ui.view`, `view-chain MODEL` |
| Button doesn't appear | `view_fields MODEL`, check `groups`, `invisible` |
| Access denied | `ir.model.access`, `ir.rule`, `res.groups` |
| Cron didn't fire | `ir.cron` (lastcall, nextcall, active) |
| Server action didn't run | `ir.actions.server`, `base.automation` |
| Email didn't send | `mail.mail`, `mail.template`, `fetchmail.server`, outgoing server config |
| Attachment missing | `ir.attachment` |
| Record was changed | chatter (`mail.message`) + `mail.tracking.value` |
| Record was deleted | `mail.message` unlink entries, or audit log addon |
| Report prints wrong | `ir.actions.report`, QWeb `ir.ui.view` |
| Module behaving differently | `ir.module.module` (write_date, latest_version) |
| Sequence number weird | `ir.sequence`, `ir.sequence.date_range` |
| Translation off | `ir.translation` (pre-v17), `_translate` on fields (v17+) |
| Scheduled action config | `ir.cron` |
| Studio-created field | `ir.model.fields` with `state=manual` or in `studio_customization` module |

## When investigation stalls

Three dead-end escapes:

1. **Dump the record raw.** `read MODEL ID` with no field restriction, pipe to a file, read every line. You almost always miss a flag.
2. **Compare to a known-good sibling.** `diff MODEL BROKEN GOOD` — the differing fields tell you exactly what's wrong.
3. **Walk the referrers.** `refs MODEL ID` — maybe the problem isn't on the record, it's on something that references it.
