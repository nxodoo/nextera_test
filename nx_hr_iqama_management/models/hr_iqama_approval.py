from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


APPROVAL_STATUS_SELECTION = [
    ('pending', 'Pending'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
]


class HrIqamaApproval(models.Model):
    _name = 'hr.iqama.approval'
    _description = 'Residency/Visa Request Approval'
    _order = 'id'

    iqama_id = fields.Many2one(
        'hr.iqama',
        string='Residency/Visa Request',
        required=True,
        ondelete='cascade',
    )
    approver_id = fields.Many2one(
        'res.users',
        string='Approver',
        required=True,
    )
    status = fields.Selection(
        APPROVAL_STATUS_SELECTION,
        string='Status',
        default='pending',
        required=True,
    )
    decision_date = fields.Datetime(string='Decision Date', readonly=True)
    comment = fields.Text(string='Comment')

    _sql_constraints = [
        (
            'iqama_approver_unique',
            'unique(iqama_id, approver_id)',
            'Each approver can only be assigned once per residency/visa request.',
        ),
    ]

    def _check_parent_locked(self):
        """Block approval-line edits once the parent request reaches a locked state."""
        locked_requests = self.mapped('iqama_id').filtered(lambda request: request.state in request._locked_states())
        if locked_requests:
            raise ValidationError(
                _('Approval lines cannot be modified once the residency/visa request is locked.')
            )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._check_parent_locked()
        return records

    def write(self, vals):
        self._check_parent_locked()
        return super().write(vals)

    def unlink(self):
        self._check_parent_locked()
        return super().unlink()

    def action_mark_approved(self):
        """Mark the approval line as approved by its assigned approver."""
        for line in self:
            if line.approver_id != self.env.user:
                raise UserError(_('Only the assigned approver can approve this request.'))
            line.write({
                'status': 'approved',
                'decision_date': fields.Datetime.now(),
            })
            line.iqama_id.message_post(
                body=_('%(approver)s approved the residency/visa request.') % {
                    'approver': line.approver_id.name,
                }
            )

    def action_mark_rejected(self):
        """Mark the approval line as rejected by its assigned approver."""
        for line in self:
            if line.approver_id != self.env.user:
                raise UserError(_('Only the assigned approver can reject this request.'))
            line.write({
                'status': 'rejected',
                'decision_date': fields.Datetime.now(),
            })
            line.iqama_id.message_post(
                body=_('%(approver)s rejected the residency/visa request.') % {
                    'approver': line.approver_id.name,
                }
            )
