# -*- coding: utf-8 -*-
from odoo import api, fields, models

class ResConfigSettings(models.TransientModel):
    """ Extend res.config.settings to add custody journal settings. """

    _inherit = 'res.config.settings'

    # -------------------------------------------------------------------------
    # FIELDS FOR CUSTODY
    # -------------------------------------------------------------------------

    custody_journal_permanent_id = fields.Many2one(
        'account.journal',
        string="Permanent Custody Journal",
        config_parameter="nx_employee_custody_management.custody_journal_permanent_id",
    )

    custody_journal_temporary_id = fields.Many2one(
        'account.journal',
        string="Temporary Custody Journal",
        config_parameter="nx_employee_custody_management.custody_journal_temporary_id",
    )

    # -------------------------------------------------------------------------
    # PRODUCT CUSTODY ACCOUNTS
    # -------------------------------------------------------------------------
    custody_product_journal_id = fields.Many2one(
        'account.journal',
        string="Product Custody Journal",
        config_parameter="nx_employee_custody_management.custody_product_journal_id",
    )

    custody_product_account_id = fields.Many2one(
        'account.account',
        string="Product Custody Account",
        config_parameter="nx_employee_custody_management.custody_product_account_id",
        help="Asset account holding the value of products under employee custody.",
    )

    custody_deduction_account_id = fields.Many2one(
        'account.account',
        string="Custody Deduction Account",
        config_parameter="nx_employee_custody_management.custody_deduction_account_id",
        help="Account charged with the deducted value when a still-valid product "
             "custody is returned (e.g. employee receivable / recovery).",
    )

