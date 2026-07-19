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

    bracket_ids = fields.One2many(
        'nx.egypt.payroll.tax.bracket', 'config_id',
        string='Tax Brackets',
        copy=True,
        default=lambda self: self._default_bracket_ids(),
    )

    # ── Test Calculation inputs ────────────────────────────────────
    test_monthly_gross = fields.Float(string='Monthly Gross Salary')
    test_annual_equivalent = fields.Float(
        string='Annual Salary Equivalent',
        compute='_compute_test_annual_equivalent', store=False,
    )
    test_personal_exemption = fields.Float(
        string='Personal Exemption Limit',
        compute='_compute_test_personal_exemption', store=False, readonly=True,
    )
    test_other_deductions = fields.Float(string='Other Monthly Deductions')
    test_additional_taxable = fields.Float(string='Additional Taxable Amount')

    # ── Test Calculation results (computed live) ───────────────────
    res_annual_gross = fields.Float(string='Annual Gross Income', compute='_compute_results')
    res_exemption_applied = fields.Float(string='Personal Exemption Applied', compute='_compute_results')
    res_other_deductions_annual = fields.Float(string='Other Deductions (Annual)', compute='_compute_results')
    res_additional_taxable = fields.Float(string='Additional Taxable Amount', compute='_compute_results')
    res_annual_taxable = fields.Float(string='Annual Taxable Income', compute='_compute_results')
    res_total_annual_tax = fields.Float(string='Total Annual Tax', compute='_compute_results')
    res_monthly_tax = fields.Float(string='Monthly Tax', compute='_compute_results')
    res_net_salary = fields.Float(string='Estimated Net Salary', compute='_compute_results')

    # Last computed monthly tax used by the Income Tax salary rule.
    monthly_tax = fields.Float(string='Last Monthly Tax', readonly=True, tracking=True)

    # ── Compute ────────────────────────────────────────────────────
    @api.depends('test_monthly_gross')
    def _compute_test_annual_equivalent(self):
        for rec in self:
            rec.test_annual_equivalent = rec.test_monthly_gross * 12.0

    @api.depends('total_exemption_limit')
    def _compute_test_personal_exemption(self):
        for rec in self:
            rec.test_personal_exemption = rec.total_exemption_limit

    @api.depends(
        'test_monthly_gross', 'test_other_deductions', 'test_additional_taxable',
        'total_exemption_limit',
        'bracket_ids.rate', 'bracket_ids.amount_from', 'bracket_ids.amount_to',
        'bracket_ids.is_active',
    )
    def _compute_results(self):
        for rec in self:
            vals = rec._simulate()
            rec.res_annual_gross = vals['annual_gross']
            rec.res_exemption_applied = vals['exemption']
            rec.res_other_deductions_annual = vals['other_annual']
            rec.res_additional_taxable = vals['additional']
            rec.res_annual_taxable = vals['taxable']
            rec.res_total_annual_tax = vals['total_annual_tax']
            rec.res_monthly_tax = vals['monthly_tax']
            rec.res_net_salary = vals['net_salary']

    def _simulate(self):
        self.ensure_one()
        annual_gross = self.test_monthly_gross * 12.0
        exemption = self.total_exemption_limit
        other_annual = self.test_other_deductions * 12.0
        additional = self.test_additional_taxable
        taxable = annual_gross - exemption - other_annual + additional
        if taxable < 0:
            taxable = 0.0
        total_annual_tax = self.compute_annual_tax(taxable)
        monthly_tax = total_annual_tax / 12.0
        net_salary = self.test_monthly_gross - monthly_tax - self.test_other_deductions
        return {
            'annual_gross': annual_gross, 'exemption': exemption,
            'other_annual': other_annual, 'additional': additional,
            'taxable': taxable, 'total_annual_tax': total_annual_tax,
            'monthly_tax': monthly_tax, 'net_salary': net_salary,
        }

    # ── Create ─────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                seq = self.env['ir.sequence'].next_by_code('nx.egypt.payroll.tax')
                vals['name'] = seq or _('Egypt Tax Version')
        return super().create(vals_list)

    # ── Tax computation ────────────────────────────────────────────
    def _get_active_brackets(self):
        self.ensure_one()
        return self.bracket_ids.filtered(lambda b: b.is_active).sorted('amount_from')

    def compute_annual_tax(self, taxable_income):
        """Progressive tax over the active numeric brackets."""
        self.ensure_one()
        if taxable_income <= 0:
            return 0.0
        total = 0.0
        for bracket in self._get_active_brackets():
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
            'monthly_tax': 0.0,
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

    # ── Default brackets (Egyptian annual matrix) ──────────────────
    @api.model
    def _default_bracket_rows(self):
        # rate, from, to, c600, c700, c800, c900, c1200, cabove, notes
        return [
            (0.0, 1, 40000, '1 to 40,000', '-', '-', '-', '-', '-', 'Zero-rate band'),
            (10.0, 40001, 55000, '40,001 to 55,000', '1 to 55,000', '-', '-', '-', '-', 'Lower tax band'),
            (15.0, 55001, 70000, '55,001 to 70,000', '55,001 to 70,000', '1 to 70,000', '-', '-', '-', 'Lower-middle tax band'),
            (20.0, 70001, 200000, '70,001 to 200,000', '70,001 to 200,000', '70,001 to 200,000', '1 to 200,000', '-', '-', 'Middle tax band'),
            (22.5, 200001, 400000, '200,001 to 400,000', '200,001 to 400,000', '200,001 to 400,000', '200,001 to 400,000', '1 to 400,000', '-', 'Upper-middle tax band'),
            (25.0, 400000, 1200000, 'Above 400,000', 'Above 400,000', 'Above 400,000', 'Above 400,000', 'Above 400,000', '1 to 1,200,000', 'High tax band'),
            (27.5, 1200000, 0, '-', '-', '-', '-', '-', 'Above 1,200,000', 'Top rate'),
        ]

    @api.model
    def _bracket_vals_from_row(self, seq, r):
        return {
            'sequence': seq * 10,
            'rate': r[0], 'amount_from': r[1], 'amount_to': r[2],
            'col_600k': r[3], 'col_700k': r[4], 'col_800k': r[5],
            'col_900k': r[6], 'col_1200k': r[7], 'col_above': r[8],
            'is_active': True, 'notes': r[9],
        }

    @api.model
    def _default_bracket_ids(self):
        return [
            (0, 0, self._bracket_vals_from_row(seq, r))
            for seq, r in enumerate(self._default_bracket_rows(), start=1)
        ]

    def action_load_default_brackets(self):
        self.ensure_one()
        self.bracket_ids = [(5, 0, 0)] + self._default_bracket_ids()
        return True

    # ── Action: Run Simulation ─────────────────────────────────────
    def action_run_simulation(self):
        self.ensure_one()
        self.monthly_tax = self._simulate()['monthly_tax']
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Simulation completed. Monthly tax calculated.'),
                'type': 'success',
                'sticky': False,
            },
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

    # ── Helper used by the EGY_TAX salary rule ─────────────────────
    @api.model
    def _get_active_version(self):
        return self.search([('state', '=', 'active')], limit=1)

    def compute_monthly_tax_for(self, monthly_gross,
                                other_monthly_deductions=0.0, additional=0.0):
        """Monthly income tax for a given employee's monthly gross salary,
        using this version's exemption limit and active brackets."""
        self.ensure_one()
        annual_gross = monthly_gross * 12.0
        other_annual = other_monthly_deductions * 12.0
        taxable = annual_gross - self.total_exemption_limit - other_annual + additional
        if taxable < 0:
            taxable = 0.0
        return self.compute_annual_tax(taxable) / 12.0
