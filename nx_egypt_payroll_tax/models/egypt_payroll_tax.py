# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class NxEgyptPayrollTax(models.Model):
    _name = 'nx.egypt.payroll.tax'
    _description = 'Egypt Payroll Tax Configuration'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'effective_date desc, id desc'

    name = fields.Char(
        string='Name',
        required=True,
        default=lambda self: _('New'),
        tracking=True,
    )
    # Created By / Created On are exposed as read-only in the form.
    created_by_id = fields.Many2one(
        'res.users', string='Created By',
        default=lambda self: self.env.user, readonly=True,
    )
    created_on = fields.Date(
        string='Created On', default=fields.Date.context_today, readonly=True,
    )
    effective_date = fields.Date(
        string='Effective Date',
        default=fields.Date.context_today,
        tracking=True,
        help='Start date on which this tax version applies.',
    )
    end_date = fields.Date(
        string='End Date', readonly=True, tracking=True,
        help='Filled automatically when a new version is created.',
    )
    total_exemption_limit = fields.Float(
        string='Total Exemption Limit',
        default=20000.0,
        tracking=True,
        help='Yearly personal exemption limit used in the tax calculation. '
             'This is the single source of the exemption value.',
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('active', 'Active'), ('inactive', 'Inactive')],
        string='Status', default='draft', required=True, tracking=True,
    )

    # Net-income range this category applies to. Payroll picks the category
    # whose [From, To] contains the employee's annual net income.
    net_income_from = fields.Float(string='From', default=0.0)
    net_income_to = fields.Float(
        string='To', default=0.0,
        help='Upper net-income bound of this category. '
             'Leave 0 for the open-ended top category.',
    )

    bracket_ids = fields.One2many(
        'nx.egypt.payroll.tax.bracket', 'config_id',
        string='Tax Brackets',
        copy=True,
    )

    # ── Create ─────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                seq = self.env['ir.sequence'].next_by_code('nx.egypt.payroll.tax')
                vals['name'] = seq or _('Egypt Tax Version')
        return super().create(vals_list)

    # ── Tax computation ────────────────────────────────────────────
    def compute_annual_tax(self, taxable_income):
        """Progressive tax over this category's numeric brackets."""
        self.ensure_one()
        if taxable_income <= 0:
            return 0.0
        total = 0.0
        for bracket in self.bracket_ids.sorted('amount_from'):
            lower = bracket.amount_from
            upper = bracket.amount_to or float('inf')
            if taxable_income <= lower:
                continue
            taxed = min(taxable_income, upper) - lower
            if taxed > 0:
                total += taxed * (bracket.rate / 100.0)
        return total

    # ── Actions: version workflow ──────────────────────────────────
    def action_activate(self):
        for rec in self:
            if rec.state == 'inactive':
                raise UserError(_('Inactive versions cannot be activated.'))
            rec.state = 'active'
        return True

    def action_set_draft(self):
        for rec in self:
            if rec.state == 'inactive':
                raise UserError(_('Inactive versions cannot be moved to draft.'))
            rec.state = 'draft'
        return True

    def action_create_new_version(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        # Close the current version.
        self.write({'state': 'inactive', 'end_date': today})
        new_version = self.copy({
            'state': 'draft',
            'effective_date': today,
            'end_date': False,
            'created_by_id': self.env.user.id,
            'created_on': today,
            'name': _('New'),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': new_version.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_versions(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tax Configuration Versions'),
            'res_model': self._name,
            'view_mode': 'list,form',
            'target': 'current',
        }

    # ── Action: Apply Monthly Tax to Salary Structure ──────────────
    def action_apply_to_salary_structure(self):
        self.ensure_one()
        # Open the structure that actually holds the Income Tax (EGY_TAX) rule.
        rule = self.env.ref('nx_egypt_payroll_tax.rule_egypt_income_tax',
                            raise_if_not_found=False)
        structure = rule.struct_id if rule else self.env['hr.payroll.structure']
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Salary Structure'),
            'res_model': 'hr.payroll.structure',
            'target': 'current',
        }
        if structure:
            action.update({'res_id': structure.id, 'view_mode': 'form'})
        else:
            action['view_mode'] = 'list,form'
        return action

    # ── Helpers used by the EGY_TAX salary rule ────────────────────
    @api.model
    def _get_active_categories(self):
        return self.search([('state', '=', 'active')])

    def _pick_for_income(self, income):
        """From this set of categories, return the one whose upper bound (To)
        is the smallest that still covers the income (To = 0 means open-ended
        top). Using the ceiling avoids gaps between adjacent ranges."""
        ordered = self.sorted(lambda c: (c.net_income_to or float('inf')))
        for cat in ordered:
            ceiling = cat.net_income_to or float('inf')
            if income <= ceiling:
                return cat
        return ordered[-1] if ordered else self.browse()

    @api.model
    def compute_employee_monthly_tax(self, monthly_gross,
                                     other_monthly_deductions=0.0, additional=0.0):
        """Monthly income tax for an employee's monthly gross salary.

        Finds the active category whose net-income range matches the
        employee's annual net income, then runs that category's progressive
        brackets.
        """
        categories = self._get_active_categories()
        if not categories:
            return 0.0
        exemption = categories[0].total_exemption_limit
        annual_gross = monthly_gross * 12.0
        other_annual = other_monthly_deductions * 12.0
        taxable = annual_gross - exemption - other_annual + additional
        if taxable < 0:
            taxable = 0.0
        category = categories._pick_for_income(taxable)
        if not category:
            return 0.0
        return category.compute_annual_tax(taxable) / 12.0
