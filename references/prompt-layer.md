# Prompt layer — asking functional implementers the right question

The job: translate between a functional ask ("fix the payroll JE") and a RPC call. This file is the question tree.

## Rule of one

Ask **one** targeted question at a time. A volley of three questions kills momentum. If more than one clarification is needed, pick the most-blocking one, resolve it, then ask the next.

## Reflect-first pattern

Before asking, reflect what you heard back in Odoo terms. Lets the user correct your framing without a round-trip.

Bad:
> What model does the batch refer to?

Good:
> You mean the payroll batch (`hr.payslip.run`) — which one (id or name)?

## The ambiguity decision tree

### "fix the payslip"
- Need id or employee name + period. Ask: `which payslip — id, employee name, or batch?`
- If they give an employee + month, resolve via `search hr.payslip --domain [["employee_id.name","ilike","X"],["date_from",">=","YYYY-MM-01"]]`.

### "the batch failed"
- `hr.payslip.run` id or name. Ask: `which batch — name or id?`
- Then `read hr.payslip.run <id>` → `slip_ids`, `state`, `move_id`.

### "the invoice is wrong"
- Model = `account.move`. Ask: `which invoice — number (INV/…), id, or customer+date?`
- Watch for `move_type`: `out_invoice`, `in_invoice`, `out_refund`, `in_refund`, `entry` (journal entry).

### "can't post"
- Always get the full traceback. Ask: `paste the server error, including the file paths and line numbers`.
- Parse the final `File` line — that's the real cause. Earlier frames are override chain.

### "a field disappeared"
- Could be: v-upgrade dropped it, group visibility, view inherit removed it, computed/related returning empty.
- Minimum: `fields MODEL --like FIELDNAME`. If missing, confirm Odoo version and check public source for that version.
- If present but hidden in UI: inspect `view_fields MODEL --view-type form` for its `invisible` expression.

### "it worked yesterday"
- Classic `trace MODEL ID` + nearby_module_upgrades. SaaS auto-upgrades silently.
- Also check `ir.cron` runs: `search_read ir.cron --domain [["active","=",true],["lastcall",">=","YYYY-MM-DD"]]`.

### "we need a report"
- Ask: `is this a QWeb PDF/HTML (print button on a form), a spreadsheet export, or a dashboard view?`
- QWeb: `report xmlid --ids N --save /tmp/out.pdf`
- Spreadsheet: use Odoo's export action or custom.
- Dashboard: usually `pivot`/`graph` views — `view MODEL --view-type pivot --xmlid …`.

### "upgrade this module"
- Confirm production vs staging. **Always.** Then `upgrade NAMES --yes`.
- Snapshot the config records the module may touch first (`hr.salary.rule`, chart of accounts, etc.) — SaaS migrations have hit us.

### "make it do X automatically"
- Automated behavior lives in `ir.cron`, `base.automation`, `ir.actions.server`, or the mail/activity planners. Ask: `should this happen on save, on a schedule, or when a specific user clicks?`

## Technical-first always

Even when the user is functional-only, your first RPC call should still be a technical inspection, not a write. Order:

1. `fields MODEL --like <what they mentioned>` — confirm the field is named what you think.
2. `view MODEL --view-type form --arch-only` — see what the UI actually shows.
3. `view_fields MODEL --view-type form` — confirm buttons and their guards.
4. `read MODEL <id>` with full default field set, no `--fields`, so you see the current state.
5. `trace MODEL <id>` only if the user is asking "why did X happen".

Then — and only then — propose the write.

## Confirming prod writes

Minimum template for a write confirmation:

> I will:
> - `write hr.salary.rule [41,42,43,44,45,47] {"analytic_distribution": false}`
> - This clears the field on 6 rules.
> - Rollback: `restore --from /tmp/pre_fix.json`.
>
> OK to run?

Never:
- Skip the ids list.
- Describe the vals in prose ("I'll clear the thing").
- Chain more than one write.
- Fire a method call (`post`, `confirm`, `done`) in the same message as the data write.

## Playwright vs RPC

Playwright when: the task hinges on what a user *sees* (RTL rendering, chatter widget, kanban drag, modal popup, print button that opens a browser PDF viewer), or on a `type="action"` button that resolves client-side.

RPC when: anything data-only, or the back-end wants to be driven by `button MODEL METHOD IDS`.

If unsure, use RPC first (cheaper, deterministic) and escalate to Playwright only when a UI-specific symptom is in play.
