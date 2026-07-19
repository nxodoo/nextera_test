# -*- coding: utf-8 -*-
from odoo import models, fields, api


class HrLetterRequest(models.Model):
    _name = 'hr.letter.request'
    _description = 'HR Letter Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: ('New'),
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        default=lambda self: self.env.user.employee_id,
        tracking=True,
    )
    letter_type = fields.Selection([
        ('experience', 'Experience Letter'),
        ('salary', 'Salary Certificate'),
        ('hr', 'HR Letter'),
        ('noc', 'No Objection Certificate'),
        ('embassy', 'Embassy Letter'),
        ('other', 'Other'),
    ], string='Letter Type', required=True, default='hr', tracking=True)
    addressed_to = fields.Char(string='Addressed To')
    reason = fields.Text(string='Reason / Notes')
    request_date = fields.Date(
        string='Request Date', default=fields.Date.context_today,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('issued', 'Issued'),
        ('refused', 'Refused'),
    ], string='Status', default='draft', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'hr.letter.request') or 'New'
        return super().create(vals_list)

    def action_submit(self):
        self.write({'state': 'submitted'})

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_issue(self):
        self.write({'state': 'issued'})

    def action_refuse(self):
        self.write({'state': 'refused'})
