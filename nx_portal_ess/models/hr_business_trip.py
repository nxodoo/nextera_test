# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class HrBusinessTrip(models.Model):
    _name = 'hr.business.trip'
    _description = 'Business Trip Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc, id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: ('New'),
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        default=lambda self: self.env.user.employee_id,
        tracking=True,
    )
    destination = fields.Char(string='Destination', required=True)
    purpose = fields.Text(string='Purpose')
    date_from = fields.Date(string='From', required=True)
    date_to = fields.Date(string='To', required=True)
    estimated_cost = fields.Monetary(string='Estimated Cost')
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('refused', 'Refused'),
        ('done', 'Completed'),
    ], string='Status', default='draft', tracking=True)

    duration = fields.Integer(string='Days', compute='_compute_duration', store=True)

    @api.depends('date_from', 'date_to')
    def _compute_duration(self):
        for rec in self:
            if rec.date_from and rec.date_to:
                rec.duration = (rec.date_to - rec.date_from).days + 1
            else:
                rec.duration = 0

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_to < rec.date_from:
                raise ValidationError('The end date cannot be before the start date.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'hr.business.trip') or 'New'
        return super().create(vals_list)

    def action_submit(self):
        self.write({'state': 'submitted'})

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_refuse(self):
        self.write({'state': 'refused'})

    def action_done(self):
        self.write({'state': 'done'})
