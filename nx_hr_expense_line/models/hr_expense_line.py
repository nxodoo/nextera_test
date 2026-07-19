from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrExpenseLine(models.Model):
    _name = "hr.expense.line"
    _description = "Expense Line"
    _order = "expense_id, sequence, id"

    sequence = fields.Integer(default=10)
    expense_id = fields.Many2one(
        "hr.expense",
        string="Expense",
        required=True,
        ondelete="cascade",
    )
    sheet_id = fields.Many2one(
        "hr.expense.sheet",
        string="Expense Report",
        related="expense_id.sheet_id",
        store=True,
        readonly=True,
    )
    expense_line_type_id = fields.Many2one(
        "hr.expense.line.type",
        string="Expense Line Type",
        required=True,
        domain="[('active', '=', True), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )
    name = fields.Char(string="Description", required=True)
    unit_amount = fields.Monetary(string="Unit Price", required=True, default=0.0, currency_field="currency_id")
    total_amount = fields.Monetary(
        string="Total",
        currency_field="currency_id",
        compute="_compute_total_amount",
        store=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "hr_expense_line_ir_attachment_rel",
        "line_id",
        "attachment_id",
        string="Attachments",
        copy=False,
    )
    company_id = fields.Many2one(
        "res.company",
        related="expense_id.company_id",
        store=True,
        readonly=True,
    )
    company_currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        readonly=True,
    )
    state = fields.Selection(related="expense_id.state", store=True, readonly=True)
    date = fields.Date(related="expense_id.date", store=True, readonly=True)
    employee_id = fields.Many2one(related="expense_id.employee_id", store=True, readonly=True)
    analytic_distribution = fields.Json(
        related="expense_id.analytic_distribution",
        readonly=True,
    )

    @api.depends("unit_amount")
    def _compute_total_amount(self):
        for line in self:
            line.total_amount = line.unit_amount

    @api.constrains("unit_amount")
    def _check_positive_amount(self):
        for line in self:
            if line.unit_amount <= 0:
                raise ValidationError(_("Expense line unit price must be greater than zero."))

    @api.constrains("expense_line_type_id", "total_amount", "currency_id", "company_id")
    def _check_max_amount(self):
        """Validate the optional maximum amount in company currency."""
        for line in self.filtered("expense_line_type_id"):
            max_amount = line.expense_line_type_id.max_amount
            if not max_amount:
                continue
            converted_total = line.currency_id._convert(
                line.total_amount,
                line.company_currency_id,
                line.company_id,
                line.expense_id.date or fields.Date.context_today(line),
            )
            if converted_total > max_amount:
                raise ValidationError(
                    _(
                        "Expense line '%(line)s' exceeds the maximum amount for type '%(type)s'.",
                        line=line.name,
                        type=line.expense_line_type_id.display_name,
                    )
                )
