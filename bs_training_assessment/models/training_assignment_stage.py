# -*- coding: utf-8 -*-

from odoo import fields, models, _
from odoo.exceptions import UserError


class TrainingAssignmentStage(models.Model):
    _name = 'training.assignment.stage'
    _description = 'Training Assignment Stage'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    code = fields.Char()
    fold = fields.Boolean(string='Folded in Kanban')
    active = fields.Boolean(default=True)

    def unlink(self):
        for stage in self:
            if stage.code in ('draft', 'submit', 'approve', 'ongoing', 'completed', 'closed'):
                raise UserError(_('Cannot delete stage "%s".', stage.name))
        return super().unlink()
