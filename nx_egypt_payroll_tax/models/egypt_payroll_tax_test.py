# -*- coding: utf-8 -*-
from odoo import api, fields, models


class NxEgyptPayrollTaxTest(models.TransientModel):
    _name = 'nx.egypt.payroll.tax.test'
    _description = 'Egypt Payroll Tax — Test Calculation'

    # ── Inputs ─────────────────────────────────────────────────────
    monthly_gross = fields.Float(string='Monthly Gross Salary')
    annual_equivalent = fields.Float(
        string='Annual Salary Equivalent', compute='_compute_results')
    personal_exemption = fields.Float(
        string='Personal Exemption Limit', compute='_compute_results')
    other_deductions = fields.Float(string='Other Monthly Deductions')
    additional_taxable = fields.Float(string='Additional Taxable Amount')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)

    # ── Results (computed live) ────────────────────────────────────
    annual_gross = fields.Float(string='Annual Gross Income', compute='_compute_results')
    exemption_applied = fields.Float(string='Personal Exemption Applied', compute='_compute_results')
    other_deductions_annual = fields.Float(string='Other Deductions (Annual)', compute='_compute_results')
    additional_amount = fields.Float(string='Additional Taxable Amount', compute='_compute_results')
    annual_taxable = fields.Float(string='Annual Taxable Income', compute='_compute_results')
    matched_category_id = fields.Many2one(
        'nx.egypt.payroll.tax', string='Matched Category', compute='_compute_results')
    total_annual_tax = fields.Float(string='Total Annual Tax', compute='_compute_results')
    monthly_tax = fields.Float(string='Monthly Tax', compute='_compute_results')
    net_salary = fields.Float(string='Estimated Net Salary', compute='_compute_results')

    @api.depends('monthly_gross', 'other_deductions', 'additional_taxable')
    def _compute_results(self):
        Tax = self.env['nx.egypt.payroll.tax']
        categories = Tax._get_active_categories()
        exemption = categories[0].total_exemption_limit if categories else 0.0
        for rec in self:
            annual_gross = rec.monthly_gross * 12.0
            other_annual = rec.other_deductions * 12.0
            taxable = annual_gross - exemption - other_annual + rec.additional_taxable
            if taxable < 0:
                taxable = 0.0
            category = categories._pick_for_income(taxable) if categories else Tax
            total_annual_tax = category.compute_annual_tax(taxable) if category else 0.0
            monthly_tax = total_annual_tax / 12.0
            rec.annual_equivalent = annual_gross
            rec.personal_exemption = exemption
            rec.annual_gross = annual_gross
            rec.exemption_applied = exemption
            rec.other_deductions_annual = other_annual
            rec.additional_amount = rec.additional_taxable
            rec.annual_taxable = taxable
            rec.matched_category_id = category.id if category else False
            rec.total_annual_tax = total_annual_tax
            rec.monthly_tax = monthly_tax
            rec.net_salary = rec.monthly_gross - monthly_tax - rec.other_deductions
