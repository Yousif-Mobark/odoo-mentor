# Recipes — ready-to-run playbooks

Each recipe is: **symptom → diagnosis commands → fix commands → verification**. Every destructive write starts with a snapshot and ends with a rollback hint. Pick the matching one, swap the placeholder ids/aliases, run.

Always substitute `<alias>` for the user's configured alias.

---

## 1. Fix bad `analytic_distribution` corrupted by SaaS migration

**Symptom**: Posting a payslip JE fails with `ValueError: invalid literal for int() with base 10: '{"1": 11}'` or similar. Traceback ends in `_prepare_analytic_distribution_line`.

**Diagnose:**
```
python3 /opt/odoo_rpc.py -a <alias> --pretty search_read hr.salary.rule \
  --domain '[["analytic_distribution","!=",false]]' \
  --fields id,name,code,struct_id,analytic_distribution,write_uid,write_date
```
Expect: several rules written at the same timestamp by uid=1 (OdooBot), all with a key that is not an integer or comma-separated integers.

Cross-check nearby module upgrades:
```
python3 /opt/odoo_rpc.py -a <alias> --pretty search_read ir.module.module \
  --domain '[["write_date",">=","YYYY-MM-DD HH:00:00"]]' \
  --fields name,write_date,write_uid --order write_date
```

**Snapshot:**
```
python3 /opt/odoo_rpc.py -a <alias> snapshot hr.salary.rule '[41,42,43,44,45,47]' \
  --to /tmp/salary_rules_pre.json
```

**Fix (option A — nuke distribution):**
```
python3 /opt/odoo_rpc.py -a <alias> write hr.salary.rule '[41,42,43,44,45,47]' \
  '{"analytic_distribution": false}'
```

**Fix (option B — set correct value):**
```
python3 /opt/odoo_rpc.py -a <alias> write hr.salary.rule '[41,42,43,44,45,47]' \
  '{"analytic_distribution": {"11": 100.0}}'
```

**Clean generated draft move_lines** (the bad key already leaked into drafts):
```
python3 /opt/odoo_rpc.py -a <alias> search account.move.line \
  --domain '[["analytic_distribution","!=",false],["parent_state","=","draft"]]'
# fetch, filter the ones whose keys are not integers (via python one-liner)
python3 /opt/odoo_rpc.py -a <alias> read account.move.line '<IDS>' --fields analytic_distribution \
  | python3 -c "import json,sys; recs=json.load(sys.stdin); bad=[]; [bad.append(r['id']) for r in recs if any(not all(c.isdigit() or c==',' for c in str(k)) for k in (r.get('analytic_distribution') or {}))]; print(json.dumps(bad))"
# then
python3 /opt/odoo_rpc.py -a <alias> write account.move.line '<BAD_IDS>' '{"analytic_distribution": false}'
```

**Verify:** `search_count hr.salary.rule --domain '[["analytic_distribution","!=",false]]'` returns 0 (option A) or your intended rows (option B). Try posting one move: `call account.move action_post --args '[[<id>]]'`.

**Rollback:** `restore --from /tmp/salary_rules_pre.json`.

---

## 2. Regenerate a payslip's missing journal entry

**Symptom**: `hr.payslip.move_id = False` but `state = 'validated'`. The move was created at validation then unlinked.

**Diagnose:**
```
python3 /opt/odoo_rpc.py -a <alias> trace hr.payslip <ID> --pretty
```
Chatter should show `move_state` tracked `'' → draft` at the validate time. Confirms the move once existed.

**Path A — cancel → draft → validate cycle (recreates JE):**
```
python3 /opt/odoo_rpc.py -a <alias> call hr.payslip action_payslip_cancel --args '[[<ID>]]'
python3 /opt/odoo_rpc.py -a <alias> call hr.payslip action_payslip_draft  --args '[[<ID>]]'
python3 /opt/odoo_rpc.py -a <alias> call hr.payslip action_payslip_done   --args '[[<ID>]]'
```

**Path B — call move-creation directly** (if your `hr.payslip` has `_action_create_account_move` exposed; it does on v18+):
```
python3 /opt/odoo_rpc.py -a <alias> call hr.payslip _action_create_account_move --args '[[<ID>]]'
```

**Verify:** `read hr.payslip <ID> --fields move_id,move_state` → both set, move draft.

---

## 3. Fix a broken view after module upgrade

**Symptom**: Form view throws ParseError. Usually a dropped field or deprecated attribute.

**Diagnose:**
```
python3 /opt/odoo_rpc.py -a <alias> view-chain MODEL --view-type form
# for each view in the chain, especially custom ones:
python3 /opt/odoo_rpc.py -a <alias> read ir.ui.view <id> --fields name,arch_updated,arch
```
Compare the inherited view against current `fields MODEL`. Any `<field name="X"/>` where X is not in current fields = break.

**Fix: edit the module's XML**, remove or rename the dropped reference, upgrade:
```
python3 /opt/odoo_rpc.py -a <alias> upgrade my_module --yes
```

For a Studio-patched view (`ir.ui.view.arch_updated` present):
```
# reset to file version
python3 /opt/odoo_rpc.py -a <alias> call ir.ui.view reset_arch --args '[[<view_id>]]'
```

---

## 4. Cross-company analytic account issue

**Symptom**: `account.move.action_post` fails with "cannot use analytic account from company X in company Y".

**Diagnose:**
```
python3 /opt/odoo_rpc.py -a <alias> read account.analytic.account <AA_ID> --fields name,company_id
python3 /opt/odoo_rpc.py -a <alias> read account.move <MOVE_ID> --fields company_id
```

**Fix option A — make the analytic account multi-company:**
```
python3 /opt/odoo_rpc.py -a <alias> write account.analytic.account <AA_ID> '{"company_id": false}'
```

**Fix option B — create a per-company copy and swap the distribution:**
```
python3 /opt/odoo_rpc.py -a <alias> create account.analytic.account \
  '{"name":"رواتب","plan_id":<PLAN_ID>,"company_id":2}'
# then rewrite distribution on the affected rules
```

---

## 5. Who deleted record X?

Odoo doesn't log unlinks on the record itself (because it's gone), but `mail.message` entries referencing it survive **if** the model has `mail.thread` inheritance.

**Diagnose:**
```
python3 /opt/odoo_rpc.py -a <alias> search_read mail.message \
  --domain '[["model","=","MODEL"],["res_id","=",<ID>]]' \
  --fields id,date,author_id,subject,body,subtype_id --order 'date desc'
```
Subtype `discussion`/`activities`/`note` lingers for a while.

For a hard forensic trail, SaaS: open support ticket (they have DB-level audit). Self-hosted: `pg_dump` + `pg_waldump`.

---

## 6. Mass-fix broken sequences

**Symptom**: New records jump a number or restart from 1 after upgrade.

**Diagnose:**
```
python3 /opt/odoo_rpc.py -a <alias> search_read ir.sequence \
  --domain '[["code","=","account.move"]]' \
  --fields name,prefix,padding,number_next,number_next_actual,implementation
```

**Fix:**
```
python3 /opt/odoo_rpc.py -a <alias> write ir.sequence <ID> \
  '{"number_next_actual": <N>, "implementation":"no_gap"}'
```

---

## 7. Re-trigger a scheduled action immediately

```
python3 /opt/odoo_rpc.py -a <alias> search_read ir.cron \
  --domain '[["name","ilike","<name>"]]' --fields id,name,active,lastcall,nextcall
# press run now:
python3 /opt/odoo_rpc.py -a <alias> call ir.cron method_direct_trigger --args '[[<id>]]'
```

---

## 8. Bulk reassign the salesperson on open quotations

```
python3 /opt/odoo_rpc.py -a <alias> search sale.order \
  --domain '[["state","in",["draft","sent"]],["user_id","=",<OLD>]]'
# then
python3 /opt/odoo_rpc.py -a <alias> write sale.order '<IDS>' '{"user_id": <NEW>}'
```

Always snapshot first for 100+ records.

---

## 9. Export a report to PDF for comparison

```
python3 /opt/odoo_rpc.py -a <alias> report hr_payroll.action_report_payslip 767,768,769 \
  --save /tmp/slips.pdf
```

If the report xmlid is unknown:
```
python3 /opt/odoo_rpc.py -a <alias> search_read ir.actions.report \
  --domain '[["model","=","hr.payslip"]]' --fields xml_id,name,report_name,report_type
```

---

## 10. Audit who upgraded modules today

```
python3 /opt/odoo_rpc.py -a <alias> search_read ir.module.module \
  --domain '[["state","=","installed"],["write_date",">=","YYYY-MM-DD"]]' \
  --fields name,display_name,write_date,write_uid,latest_version --order write_date
```

OdooBot (uid=1) at identical sub-minute timestamps = SaaS auto-upgrade. Any other uid at business hours = someone pressed the button in the UI.

---

Each recipe is linear by design. If a step fails, STOP and diagnose — don't skip ahead to "force" the next step. The patterns in `investigation.md` apply.
