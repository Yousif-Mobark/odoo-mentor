# Example session — Odoo 19 SaaS payslip JE post failure

A real diagnostic run against bluehills.odoo.com on 2026-10-26. User reported `action_post` failing on a payslip JE.

## Transcript

### Step 1 — connect

```
$ python3 /opt/odoo_rpc.py --pretty db-list https://bluehills.odoo.com
[
  "bluehills25-bluehills-main-21670787"
]
$ python3 /opt/odoo_rpc.py config add bluehills \
    --url https://bluehills.odoo.com \
    --db bluehills25-bluehills-main-21670787 \
    --login admin@bluehills.com --password 'XXXX'
Saved alias 'bluehills' (default)
$ python3 /opt/odoo_rpc.py -a bluehills check
OK  uid=2  db=bluehills25-...  login=admin@bluehills.com
Server version: 19.0+e ([19, 0, 0, 'final', 0, 'e'])
```

### Step 2 — read the failing record

```
$ python3 /opt/odoo_rpc.py -a bluehills --pretty read hr.payslip 767
# ... (full dump)
# state: validated, move_id: false  ← suspicious
```

### Step 3 — trace it

```
$ python3 /opt/odoo_rpc.py -a bluehills --pretty trace hr.payslip 734
# chatter shows move_state tracked '' → draft at validate time
# nearby_module_upgrades: l10n_sa_hr_payroll upgraded same day at 18:22:24
```

### Step 4 — scope the corruption

The user pasted the server traceback. The culprit was `int('{"1": 11}')` in `_prepare_analytic_distribution_line`. Find every source of the bad value:

```
$ python3 /opt/odoo_rpc.py -a bluehills --pretty search_read hr.salary.rule \
    --domain '[["analytic_distribution","!=",false]]' \
    --fields name,code,struct_id,analytic_distribution,write_uid,write_date
# 6 rules on struct 4 "Saudi Arabia: Monthly Pay"
# all written by uid=1 (OdooBot) at 2026-10-26 18:22:35
# all with the same corrupted key: {"1": 11}
```

### Step 5 — confirm migration-time cause

```
$ python3 /opt/odoo_rpc.py -a bluehills --pretty search_read ir.module.module \
    --domain '[["state","=","installed"],["write_date",">=","2026-10-26 18:00:00"]]' \
    --fields name,write_date,write_uid --order write_date
# Massive block of modules upgraded by Administrator at 18:22:08
# Then OdooBot auto-triggers at 18:22:11 → 18:22:35
# l10n_sa_hr_payroll finished at 18:22:24 — 10s before the rule write
```

Diagnosis: SaaS v18 → v19 migration script for `hr_payroll_account` or `l10n_sa_hr_payroll` corrupted `hr.salary.rule.analytic_distribution` (now `fields.Json` in v19). Not custom code.

### Step 6 — snapshot

```
$ python3 /opt/odoo_rpc.py -a bluehills snapshot hr.salary.rule '[41,42,43,44,45,47]' \
    --to /tmp/salary_rules_pre.json
Wrote 6 records to /tmp/salary_rules_pre.json
```

### Step 7 — patch rules

```
$ python3 /opt/odoo_rpc.py -a bluehills write hr.salary.rule '[41,42,43,44,45,47]' \
    '{"analytic_distribution": false}'
true
```

### Step 8 — clean leaked draft move_lines

```
$ python3 /opt/odoo_rpc.py -a bluehills search account.move.line \
    --domain '[["analytic_distribution","!=",false],["parent_state","=","draft"]]'
[33777, 33778, 51080, 51226, ..., 51262]
# fetch and filter to only lines where the key is not integer-only
$ python3 /opt/odoo_rpc.py -a bluehills read account.move.line '[...]' --fields analytic_distribution \
  | python3 -c "import json,sys; recs=json.load(sys.stdin); ... print(json.dumps(bad))"
[51226, 51227, 51228, 51229, 51232, 51233, 51234, 51235, 51236, 51240, 51241, 51242, 51245, 51246, 51247, 51248, 51260, 51261, 51262]
$ python3 /opt/odoo_rpc.py -a bluehills write account.move.line '[...]' '{"analytic_distribution": false}'
true
```

### Step 9 — verify

```
$ python3 /opt/odoo_rpc.py -a bluehills --pretty search_read account.move.line \
    --domain '[["move_id","=",17678]]' --fields name,analytic_distribution
# all analytic_distribution: false — ready to post
```

### Rollback (if needed)

```
$ python3 /opt/odoo_rpc.py -a bluehills restore --from /tmp/salary_rules_pre.json
Restored 6 records from /tmp/salary_rules_pre.json into hr.salary.rule
```

## Lessons encoded in the skill

- **`trace` is the first diagnostic.** Chatter + nearby module upgrades caught migration-time corruption in one call.
- **Scope before you fix.** 19 draft move_lines carried the leak; patching only rules would have left draft moves un-postable.
- **Snapshot is cheap insurance.** 6 records = 2kB JSON. One `restore` call to undo.
- **Pattern: `write_uid=1` + identical sub-minute `write_date` across rows = script/migration, never UI.**
