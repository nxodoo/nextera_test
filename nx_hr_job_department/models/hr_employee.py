# -*- coding: utf-8 -*-
from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # Restrict the selectable job positions:
    #   * job positions without a department are always available;
    #   * job positions tied to a department are only available when that
    #     department is the one selected on the employee.
    # Setting the domain at the field level makes it apply in every view,
    # regardless of which module renders the job_id field.
    job_id = fields.Many2one(
        domain="['|', ('department_id', '=', False),"
               " ('department_id', '=', department_id)]",
    )
