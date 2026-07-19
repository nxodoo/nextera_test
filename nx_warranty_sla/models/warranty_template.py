from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WarrantyTemplate(models.Model):
    _name = "warranty.template"
    _description = "Warranty Template"
    _order = "name"

    name = fields.Char(required=True)
    service_hours_per_day = fields.Float(default=8.0)
    service_days_per_week = fields.Integer(default=5)
    duration_type = fields.Selection(
        [
            ("months", "Months"),
            ("fixed_dates", "Fixed Dates"),
            ("tickets_based", "Tickets Based"),
        ],
        required=True,
        default="months",
    )
    duration_months = fields.Integer(default=0)
    total_tickets = fields.Integer(default=0)
    description = fields.Text()
    active = fields.Boolean(default=True)

    @api.constrains("service_hours_per_day", "service_days_per_week", "duration_months", "total_tickets")
    def _check_non_negative_values(self):
        for rec in self:
            if rec.service_hours_per_day < 0:
                raise ValidationError(_("Service hours per day must be >= 0."))
            if rec.service_days_per_week < 0 or rec.service_days_per_week > 7:
                raise ValidationError(_("Service days per week must be between 0 and 7."))
            if rec.duration_months < 0:
                raise ValidationError(_("Duration months must be >= 0."))
            if rec.total_tickets < 0:
                raise ValidationError(_("Total tickets must be >= 0."))
