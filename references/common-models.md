# Common-model map by domain

Short reference of model names, state fields, and common action methods — what a functional implementer usually calls out by business name.

Odoo-version drift noted inline where relevant.

## Accounting

| Business term | Model | Key fields | State machine | Common methods |
|--|--|--|--|--|
| Invoice / Bill / Journal Entry | `account.move` | `move_type` (out_invoice, in_invoice, out_refund, in_refund, entry), `state` (draft/posted/cancel), `name` (SEQ), `partner_id`, `invoice_date`, `date`, `amount_total`, `move_id` (none — this IS the move) | draft → posted → cancel | `action_post`, `button_draft`, `button_cancel`, `action_register_payment` |
| Journal item (line) | `account.move.line` | `account_id`, `partner_id`, `debit`, `credit`, `analytic_distribution`, `move_id`, `parent_state` | follows `move_id.state` | — |
| Payment | `account.payment` | `state`, `payment_type`, `partner_type`, `amount`, `journal_id`, `move_id` | draft → in_process → paid / cancel | `action_post`, `action_cancel` |
| Analytic account | `account.analytic.account` | `name`, `plan_id`, `code`, `company_id`, `balance` | n/a | — |
| Analytic plan | `account.analytic.plan` | `name`, `account_ids` | n/a | — |
| Reconciliation | `account.move.line` with `account_id.reconcile=True` + `full_reconcile_id` | — | — | `reconcile`, `remove_move_reconcile` |
| Fiscal year lock | `res.company` | `fiscalyear_lock_date`, `tax_lock_date`, `period_lock_date` | — | — |

Common pitfall: `analytic_distribution` is `fields.Json` since v17. Valid shapes: `{"<id>": pct}` or `{"id,id,id": pct}` (multi-plan). Anything else (JSON dict as key) is corruption; see `recipes.md`.

## Payroll (hr_payroll + hr_payroll_account)

| Business term | Model | Key fields | State machine | Common methods |
|--|--|--|--|--|
| Payslip | `hr.payslip` | `employee_id`, `date_from`, `date_to`, `state` (draft/validated/paid/cancel), `move_id`, `struct_id`, `net_wage` | draft → validated → paid | `compute_sheet`, `action_payslip_done`, `action_register_payment`, `action_payslip_cancel`, `action_payslip_draft` |
| Payslip line | `hr.payslip.line` | `category_id`, `code`, `total`, `salary_rule_id` | — | — |
| Batch | `hr.payslip.run` | `name`, `state`, `slip_ids`, `move_id`, `payslip_count` | 01_ready → 02_close | `action_close`, `action_draft` |
| Salary rule | `hr.salary.rule` | `code`, `name`, `category_id`, `struct_id`, `account_debit`, `account_credit`, `analytic_distribution` (Json), `amount_select` | — | — |
| Salary structure | `hr.payroll.structure` | `name`, `rule_ids`, `type_id` | — | — |
| Structure type | `hr.payroll.structure.type` | `name`, `country_id` | — | — |
| Contract / Version | `hr.contract` (<= v17) / `hr.version` (v18+) | `employee_id`, `wage`, `date_start`, `date_end`, `state` (<= v17), `analytic_distribution` | — | — |
| Employee | `hr.employee` | `name`, `department_id`, `job_id`, `company_id`, `bank_account_id` (v19 `active_bank_id`) | — | — |

v18→v19 drops: `hr.payslip.contract_id`, `hr.payslip.number`. Use `version_id` + sequence from `hr.payslip.run`.

## Sales

| Business term | Model | Key fields | State machine | Common methods |
|--|--|--|--|--|
| Sale order | `sale.order` | `partner_id`, `date_order`, `state` (draft/sent/sale/done/cancel), `order_line`, `amount_total` | draft → sale → done | `action_confirm`, `action_cancel`, `action_quotation_send` |
| Order line | `sale.order.line` | `product_id`, `product_uom_qty`, `price_unit`, `tax_id` | — | — |
| Delivery | `stock.picking` | `picking_type_id`, `state`, `move_ids` | — | `button_validate` |

## Purchase

| Business term | Model | Key fields | State machine | Common methods |
|--|--|--|--|--|
| RFQ / Purchase order | `purchase.order` | `partner_id`, `state` (draft/sent/to_approve/purchase/done/cancel), `order_line`, `amount_total` | draft → purchase | `button_confirm`, `button_cancel`, `button_approve` |
| Vendor bill | `account.move` with `move_type='in_invoice'` | — | — | `action_post` |

## Inventory

| Business term | Model | Key fields | State machine | Common methods |
|--|--|--|--|--|
| Picking | `stock.picking` | `location_id`, `location_dest_id`, `move_ids`, `state` (draft/waiting/confirmed/assigned/done/cancel) | draft → assigned → done | `button_validate`, `action_assign`, `action_cancel` |
| Move | `stock.move` | `product_id`, `product_uom_qty`, `location_id`, `location_dest_id` | — | — |
| Lot / Serial | `stock.lot` | `name`, `product_id`, `product_qty` | — | — |
| Warehouse | `stock.warehouse` | `code`, `partner_id` | — | — |
| Location | `stock.location` | `usage` (internal/supplier/customer/view/inventory/production/transit) | — | — |

## HR

| Business term | Model | Key fields | State machine | Common methods |
|--|--|--|--|--|
| Employee | `hr.employee` | see payroll section | — | — |
| Department | `hr.department` | `name`, `manager_id`, `parent_id` | — | — |
| Job position | `hr.job` | `name`, `department_id` | — | — |
| Time off / Leave | `hr.leave` | `employee_id`, `holiday_status_id`, `date_from`, `date_to`, `state` (draft/confirm/validate/refuse) | draft → confirm → validate | `action_validate`, `action_refuse`, `action_approve` |
| Attendance | `hr.attendance` | `employee_id`, `check_in`, `check_out`, `worked_hours` | — | — |
| Expense | `hr.expense` | `employee_id`, `product_id`, `total_amount`, `state` (draft/reported/approved/done/refused) | draft → done | `action_submit_expenses`, `approve_expense_sheets` |

## Project / Timesheet

| Business term | Model | Key fields | State machine | Common methods |
|--|--|--|--|--|
| Project | `project.project` | `name`, `partner_id`, `analytic_account_id` | — | — |
| Task | `project.task` | `name`, `project_id`, `stage_id`, `user_ids`, `date_deadline` | kanban stages | — |
| Timesheet | `account.analytic.line` | `project_id`, `task_id`, `employee_id`, `unit_amount`, `date` | — | — |

## CRM

| Business term | Model | Key fields | State machine | Common methods |
|--|--|--|--|--|
| Lead | `crm.lead` | `name`, `partner_id`, `type` (lead/opportunity), `stage_id`, `probability`, `expected_revenue` | kanban stages | `action_set_won_rainbowman`, `action_set_lost` |

## Infrastructure models worth knowing

| Model | Purpose |
|--|--|
| `ir.model` | Every model installed |
| `ir.model.fields` | Every field on every model, including `state` (base/manual/custom) |
| `ir.model.data` | External IDs (xmlids) → (model, res_id) |
| `ir.ui.view` | Every view (form, list, kanban, search, qweb, …) |
| `ir.ui.menu` | Menu items |
| `ir.actions.act_window` / `ir.actions.server` / `ir.actions.report` / `ir.actions.client` | Actions |
| `ir.module.module` | Installed modules, state, latest_version, write_date |
| `ir.cron` | Scheduled actions |
| `base.automation` | No-code triggers |
| `ir.rule` | Record rules |
| `ir.model.access` | ACL on model+group |
| `res.groups` | Security groups |
| `res.users` | Users |
| `res.company` | Companies (and the lock dates) |
| `res.partner` | Partners (customers, vendors, employees' partner, companies) |
| `res.currency` + `res.currency.rate` | Currencies and daily rates |
| `mail.message` | Chatter messages (notes, mails, logs, tracking changes) |
| `mail.tracking.value` | Per-field before/after when a tracked field changes |
| `mail.activity` | Scheduled activities |
| `ir.attachment` | File attachments on any record |
| `ir.sequence` | Sequence generators for numbering |

## Country localization pack naming

Odoo l10n modules follow `l10n_<country_code>[_feature]`. Common Saudi-stack:

- `l10n_sa` — Saudi Arabia Accounting
- `l10n_sa_edi` — ZATCA e-invoicing
- `l10n_sa_hr_payroll` — Saudi Payroll (defines `Saudi Arabia: Monthly Pay` struct)
- `l10n_sa_hr_payroll_account` — Payroll accounting bridge
- `l10n_sa_withholding_tax` — Withholding tax
- `l10n_gcc_invoice` — GCC invoice adaptations

When a tenant complains about country-specific behavior, grep the enterprise checkout for its l10n folder.
