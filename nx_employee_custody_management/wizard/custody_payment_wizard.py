from odoo import models, fields, api
from odoo.exceptions import UserError


class CustodyBillPaymentWizard(models.TransientModel):
    _name = "custody.bill.payment.wizard"
    _description = "Pay Vendor Bill Using Employee Custody"

    bill_id = fields.Many2one(
        'account.move',
        string="Vendor Bill",
        required=True,
        readonly=True
    )

    employee_id = fields.Many2one(
        'hr.employee',
        string="Custody Holder",
        required=True
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        string="Available Custody Holders",
        compute="_compute_employee_ids",
    )

    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
        readonly=True
    )

    balance = fields.Monetary(
        string="Custody Balance",
        currency_field="currency_id",
        compute="_compute_balance",
        readonly=True
    )

    custody_account_id = fields.Many2one(
        'account.account',
        string="Custody Account",
        related="journal_id.default_account_id",
    )

    amount = fields.Monetary(
        string="Payment Amount",
        required=True,
        currency_field="currency_id"
    )

    remaining_amount = fields.Monetary(
        string="Remaining Amount",
        compute="_compute_remaining_amount",
        currency_field="currency_id",
        readonly=True
    )

    journal_id = fields.Many2one(
        "account.journal",
        string="Custody Journal",
        domain="[('type','in',['cash', 'bank'])]",
    )
    journal_ids = fields.Many2many(
        "account.journal",
        string="Available Custody Journals",
    )

    payment_method_line_id = fields.Many2one(
        'account.payment.method.line',
        string="Payment Method",
        domain="[('journal_id','=',journal_id), ('payment_type','=','outbound')]",
        required=True
    )

    payment_date = fields.Date(
        string="Payment Date",
        default=fields.Date.context_today,
        required=True
    )

    memo = fields.Char(string="Memo", required=True)

    # ----------------------------------------------
    # COMPUTES
    # ----------------------------------------------

    @api.depends('employee_id', 'custody_account_id')
    def _compute_balance(self):
        for wiz in self:
            if wiz.employee_id:
                partner_id = wiz.employee_id.work_contact_id.id

                lines = self.env['account.move.line'].sudo().search([
                    ('partner_id', '=', partner_id),
                    ('parent_state', '=', 'posted'),
                    ('account_id', '=', wiz.custody_account_id.id)
                ])
                wiz.balance = sum(lines.mapped('debit')) - sum(lines.mapped('credit'))
            else:
                wiz.balance = 0

    @api.depends('bill_id')
    def _compute_remaining_amount(self):
        for wiz in self:
            if wiz.bill_id:
                wiz.remaining_amount = wiz.bill_id.amount_residual
            else:
                wiz.remaining_amount = 0

    @api.depends('journal_id')
    def _compute_employee_ids(self):
        param = self.env['ir.config_parameter'].sudo()
        temporary_id = param.get_param('nx_employee_custody_management.custody_journal_temporary_id')
        permanent_id = param.get_param('nx_employee_custody_management.custody_journal_permanent_id')
        for wiz in self:
            if wiz.journal_id:
                if wiz.journal_id.id == int(temporary_id):
                    employees = self.env['custody.request'].search([('is_temporary', '=', True)]).mapped('employee_id')
                    wiz.employee_ids = employees
                elif wiz.journal_id.id == int(permanent_id):
                    employees = self.env['custody.request'].search([('is_temporary', '=', False)]).mapped('employee_id')
                    wiz.employee_ids = employees
                else:
                    wiz.employee_ids = self.env['hr.employee'].browse()
            else:
                wiz.employee_ids = self.env['hr.employee'].browse()

    # ----------------------------------------------
    # CONSTRAINS
    # ----------------------------------------------

    @api.constrains('amount')
    def _check_amount(self):
        for wiz in self:
            if wiz.amount <= 0:
                raise UserError("Amount must be greater than zero!")

            if wiz.amount > wiz.balance:
                raise UserError("Amount exceeds Custody Holder custody balance!")

            if wiz.amount > wiz.remaining_amount:
                raise UserError("Amount exceeds bill remaining amount!")

    # ----------------------------------------------
    # CREATE PAYMENT
    # ----------------------------------------------

    def action_create_payment(self):
        self.ensure_one()

        # 1) Create
        payment = self._create_payment()

        # 2) Post
        self._post_payment(payment)

        # 3) Reconcile
        self._reconcile_payment(payment)

        # close wizard
        return {'type': 'ir.actions.act_window_close'}

    def _create_payment_vals(self):
        self.ensure_one()

        return {
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'memo': self.memo,
            'partner_id': self.bill_id.partner_id.id,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'date': self.payment_date,
            'journal_id': self.journal_id.id,
            'payment_method_line_id': self.payment_method_line_id.id,
            'payment_reference': f"Custody Payment - {self.bill_id.name}",
            'employee_id': self.employee_id.id,
            'custody_account_id': self.custody_account_id.id,
            'is_custody_payment': True,
        }

    def _create_payment(self):
        """Create (but do not post) the payment."""
        payment_vals = self._create_payment_vals()
        payment = self.env['account.payment'].create(payment_vals)
        return payment

    def _post_payment(self, payment):
        payment.with_context(skip_sale_auto_invoice_send=True).action_post()

    def _reconcile_payment(self, payment):

        if not self.bill_id:
            return

        domain = [
            ('parent_state', '=', 'posted'),
            ('account_type', 'in', self.env['account.payment']._get_valid_payment_account_types()),
            ('reconciled', '=', False),
        ]

        payment_lines = payment.move_id.line_ids.filtered_domain(domain)
        bill_lines = self.bill_id.line_ids.filtered_domain(domain)

        for account in payment_lines.account_id:
            (payment_lines + bill_lines) \
                .filtered_domain([
                ('account_id', '=', account.id),
                ('reconciled', '=', False),
                ('parent_state', '=', 'posted'),
            ]) \
                .reconcile()

        # Link payment to bill (optional)
        bill_lines.move_id.matched_payment_ids += payment

    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Force compute journal_ids
        param = self.env['ir.config_parameter'].sudo()
        temporary_id = param.get_param('nx_employee_custody_management.custody_journal_temporary_id')
        permanent_id = param.get_param('nx_employee_custody_management.custody_journal_permanent_id')
        journal_ids = [int(x) for x in [temporary_id, permanent_id] if
                       x and self.env['account.journal'].browse(int(x)).exists()]
        res['journal_ids'] = [(6, 0, journal_ids)]
        return res

    # ----------------------------------------------
    # ONCHANGE
    # ---------------------------------------------
    @api.onchange('journal_id')
    def _onchange_journal_id(self):
        for wizard in self:
            wizard.payment_method_line_id = False

            if wizard.journal_id:
                method_line = self.env['account.payment.method.line'].search([
                    ('journal_id', '=', wizard.journal_id.id),
                    ('payment_type', '=', 'outbound'),
                ], limit=1)
                wizard.payment_method_line_id = method_line
