from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command


class HrExpense(models.Model):
    _inherit = "hr.expense"

    expense_line_ids = fields.One2many(
        "hr.expense.line",
        "expense_id",
        string="Expense Lines",
        copy=True,
    )
    has_expense_lines = fields.Boolean(compute="_compute_has_expense_lines")

    @api.depends("expense_line_ids")
    def _compute_has_expense_lines(self):
        for expense in self:
            expense.has_expense_lines = bool(expense.expense_line_ids)

    @api.depends("expense_line_ids.currency_id")
    def _compute_currency_id(self):
        super()._compute_currency_id()
        for expense in self.filtered("expense_line_ids"):
            expense.currency_id = expense.expense_line_ids[0].currency_id

    @api.depends("expense_line_ids.total_amount")
    def _compute_total_amount_currency(self):
        expenses_with_lines = self.filtered("expense_line_ids")
        super(HrExpense, self - expenses_with_lines)._compute_total_amount_currency()
        for expense in expenses_with_lines:
            expense.total_amount_currency = sum(expense.expense_line_ids.mapped("total_amount"))

    @api.depends("expense_line_ids.expense_line_type_id")
    def _compute_account_id(self):
        expenses_with_lines = self.filtered("expense_line_ids")
        super(HrExpense, self - expenses_with_lines)._compute_account_id()
        for expense in expenses_with_lines:
            first_account = expense.expense_line_ids[:1].expense_line_type_id.account_id
            expense.account_id = first_account

    @api.depends("expense_line_ids")
    def _compute_name(self):
        expenses_with_lines = self.filtered("expense_line_ids")
        super(HrExpense, self - expenses_with_lines)._compute_name()
        for expense in expenses_with_lines:
            expense.name = expense.name or _("Detailed Expense")

    @api.model
    def _sync_line_based_amount_vals(self, vals):
        """Keep mandatory amount fields aligned when the expense is driven by lines."""
        line_commands = vals.get("expense_line_ids") or []
        if not line_commands:
            return vals

        total_amount_currency = 0.0
        line_currency_id = vals.get("currency_id")
        for command in line_commands:
            if not isinstance(command, (list, tuple)) or len(command) < 3:
                continue
            operation, _record_id, command_vals = command
            if operation != Command.CREATE or not isinstance(command_vals, dict):
                continue
            total_amount_currency += command_vals.get("unit_amount", 0.0)
            line_currency_id = line_currency_id or command_vals.get("currency_id")

        if total_amount_currency:
            vals.setdefault("quantity", 1.0)
            vals["total_amount_currency"] = total_amount_currency
            vals["price_unit"] = total_amount_currency
        if line_currency_id:
            vals["currency_id"] = line_currency_id
        return vals

    def _sync_existing_line_based_amount_vals(self, vals):
        """Recompute totals from the full resulting line set during expense updates."""
        self.ensure_one()
        line_commands = vals.get("expense_line_ids") or []
        if not line_commands:
            return vals

        line_amounts = {line.id: line.unit_amount for line in self.expense_line_ids}
        line_currencies = {line.id: line.currency_id.id for line in self.expense_line_ids if line.currency_id}
        next_virtual_id = -1

        for command in line_commands:
            if not isinstance(command, (list, tuple)) or not command:
                continue

            operation = command[0]
            record_id = command[1] if len(command) > 1 else False
            command_vals = command[2] if len(command) > 2 and isinstance(command[2], dict) else {}

            if operation == Command.CREATE:
                line_amounts[next_virtual_id] = command_vals.get("unit_amount", 0.0)
                currency_id = command_vals.get("currency_id")
                if currency_id:
                    line_currencies[next_virtual_id] = currency_id
                next_virtual_id -= 1
            elif operation == Command.UPDATE and record_id in line_amounts:
                if "unit_amount" in command_vals:
                    line_amounts[record_id] = command_vals.get("unit_amount", 0.0)
                if "currency_id" in command_vals:
                    if command_vals.get("currency_id"):
                        line_currencies[record_id] = command_vals["currency_id"]
                    else:
                        line_currencies.pop(record_id, None)
            elif operation in (Command.DELETE, Command.UNLINK):
                line_amounts.pop(record_id, None)
                line_currencies.pop(record_id, None)
            elif operation == Command.CLEAR:
                line_amounts = {}
                line_currencies = {}

        total_amount_currency = sum(line_amounts.values())
        if line_amounts:
            vals.setdefault("quantity", 1.0)
            vals["total_amount_currency"] = total_amount_currency
            vals["price_unit"] = total_amount_currency

        currency_candidates = list(line_currencies.values())
        if currency_candidates:
            vals["currency_id"] = currency_candidates[0]
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        synced_vals_list = [self._sync_line_based_amount_vals(dict(vals)) for vals in vals_list]
        return super().create(synced_vals_list)

    def write(self, vals):
        if "expense_line_ids" not in vals:
            return super().write(vals)

        result = True
        for expense in self:
            expense_vals = expense._sync_existing_line_based_amount_vals(dict(vals))
            result = super(HrExpense, expense).write(expense_vals) and result
        return result

    @api.constrains("expense_line_ids")
    def _check_expense_lines_currency(self):
        """Keep all lines aligned with the expense currency for accurate totals."""
        for expense in self.filtered("expense_line_ids"):
            currencies = expense.expense_line_ids.mapped("currency_id")
            if len(currencies) > 1:
                raise ValidationError(_("All expense lines must use the same currency."))

    def _validate_expense_lines(self):
        """Ensure detailed expenses contain at least one line before workflow actions."""
        for expense in self:
            if not expense.expense_line_ids:
                raise ValidationError(_("You cannot continue without at least one expense line."))

    def action_submit_expenses(self):
        self._validate_expense_lines()
        return super().action_submit_expenses()

    def _prepare_move_line_name(self, expense_line=None):
        """Return an accounting label for an expense or one of its detailed lines."""
        self.ensure_one()
        if expense_line:
            return _(
                "%(employee)s: %(line)s",
                employee=self.employee_id.name,
                line=expense_line.name,
            )
        return self._get_move_line_name()

    def _prepare_account_move_line_values(self):
        """Build vendor bill lines from detailed expense lines."""
        self.ensure_one()
        if not self.expense_line_ids:
            return [Command.create(super()._prepare_move_lines_vals())]

        commands = []
        for line in self.expense_line_ids:
            commands.append(Command.create({
                "name": self._prepare_move_line_name(expense_line=line),
                "account_id": line.expense_line_type_id.account_id.id,
                "quantity": 1.0,
                "price_unit": line.total_amount,
                "product_id": False,
                "product_uom_id": False,
                "analytic_distribution": self.analytic_distribution,
                "expense_id": self.id,
                "partner_id": False if self.payment_mode == "company_account" else self.employee_id.sudo().work_contact_id.id,
                "tax_ids": [Command.set(self.tax_ids.ids)],
                "currency_id": line.currency_id.id,
            }))
        return commands

    def _prepare_move_lines_vals(self):
        self.ensure_one()
        if not self.expense_line_ids:
            return super()._prepare_move_lines_vals()
        line = self.expense_line_ids[:1]
        return {
            "name": self._prepare_move_line_name(expense_line=line),
            "account_id": line.expense_line_type_id.account_id.id,
            "quantity": 1.0,
            "price_unit": line.total_amount,
            "product_id": False,
            "product_uom_id": False,
            "analytic_distribution": self.analytic_distribution,
            "expense_id": self.id,
            "partner_id": False if self.payment_mode == "company_account" else self.employee_id.sudo().work_contact_id.id,
            "tax_ids": [Command.set(self.tax_ids.ids)],
        }

    def _prepare_payments_vals(self):
        """Create company-paid accounting lines from detailed expense lines."""
        self.ensure_one()
        if not self.expense_line_ids:
            return super()._prepare_payments_vals()

        journal = self.sheet_id.journal_id
        payment_method_line = self.sheet_id.payment_method_line_id
        if not payment_method_line:
            raise UserError(_("You need to add a manual payment method on the journal (%s).") % journal.name)

        AccountTax = self.env["account.tax"]
        rate = abs(self.total_amount_currency / self.total_amount) if self.total_amount else 0.0
        base_lines = []
        for expense_line in self.expense_line_ids:
            base_lines.append(self._prepare_base_line_for_taxes_computation(
                price_unit=expense_line.total_amount,
                quantity=1.0,
                account_id=expense_line.expense_line_type_id.account_id,
                rate=rate,
            ))

        AccountTax._add_tax_details_in_base_lines(base_lines, self.company_id)
        AccountTax._round_base_lines_tax_details(base_lines, self.company_id)
        AccountTax._add_accounting_data_in_base_lines_tax_details(
            base_lines,
            self.company_id,
            include_caba_tags=self.payment_mode == "company_account",
        )
        tax_results = AccountTax._prepare_tax_lines(base_lines, self.company_id)

        move_lines = []
        for expense_line, (base_line, to_update) in zip(self.expense_line_ids, tax_results["base_lines_to_update"]):
            move_lines.append({
                "name": self._prepare_move_line_name(expense_line=expense_line),
                "account_id": base_line["account_id"].id,
                "product_id": False,
                "analytic_distribution": self.analytic_distribution,
                "expense_id": self.id,
                "tax_ids": [Command.set(base_line["tax_ids"].ids)],
                "tax_tag_ids": to_update["tax_tag_ids"],
                "amount_currency": to_update["amount_currency"],
                "balance": to_update["balance"],
                "currency_id": base_line["currency_id"].id,
                "partner_id": self.vendor_id.id,
                "quantity": 1.0,
            })

        for tax_line in tax_results["tax_lines_to_add"]:
            move_lines.append(tax_line)

        move_lines.append({
            "name": self._get_move_line_name(),
            "account_id": self.sheet_id._get_expense_account_destination(),
            "balance": -self.total_amount,
            "amount_currency": self.currency_id.round(-self.total_amount_currency),
            "currency_id": self.currency_id.id,
            "partner_id": self.vendor_id.id,
        })
        payment_vals = {
            "date": self.date,
            "memo": self.name,
            "journal_id": journal.id,
            "amount": self.total_amount_currency,
            "payment_type": "outbound",
            "partner_type": "supplier",
            "partner_id": self.vendor_id.id,
            "currency_id": self.currency_id.id,
            "payment_method_line_id": payment_method_line.id,
            "company_id": self.company_id.id,
        }
        move_vals = {
            **self.sheet_id._prepare_move_vals(),
            "ref": self.name,
            "date": self.date,
            "journal_id": journal.id,
            "partner_id": self.vendor_id.id,
            "currency_id": self.currency_id.id,
            "line_ids": [Command.create(line) for line in move_lines],
            "attachment_ids": [
                Command.create(attachment.copy_data({"res_model": "account.move", "res_id": False, "raw": attachment.raw})[0])
                for attachment in self.message_main_attachment_id | self.expense_line_ids.attachment_ids
            ],
        }
        return move_vals, payment_vals


class HrExpenseSheet(models.Model):
    _inherit = "hr.expense.sheet"

    expense_detail_line_ids = fields.One2many(
        "hr.expense.line",
        "sheet_id",
        string="Expense Detail Lines",
        readonly=True,
    )

    def action_approve_expense_sheets(self):
        self.mapped("expense_line_ids")._validate_expense_lines()
        return super().action_approve_expense_sheets()

    def _prepare_bills_vals(self):
        self.ensure_one()
        move_vals = self._prepare_move_vals()
        if self.employee_id.sudo().bank_account_id:
            move_vals["partner_bank_id"] = self.employee_id.sudo().bank_account_id.id

        line_commands = []
        for expense in self.expense_line_ids:
            line_commands.extend(expense._prepare_account_move_line_values())

        return {
            **move_vals,
            "journal_id": self.journal_id.id,
            "ref": self.name,
            "move_type": "in_invoice",
            "partner_id": self.employee_id.sudo().work_contact_id.id,
            "commercial_partner_id": self.employee_id.user_partner_id.id,
            "currency_id": self.currency_id.id,
            "line_ids": line_commands,
            "attachment_ids": [
                Command.create(attachment.copy_data({"res_model": "account.move", "res_id": False, "raw": attachment.raw})[0])
                for attachment in self.expense_line_ids.message_main_attachment_id | self.expense_line_ids.expense_line_ids.attachment_ids
            ],
        }
