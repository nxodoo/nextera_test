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
    # ASSET CUSTODY ACCOUNTS
    # -------------------------------------------------------------------------
    custody_asset_journal_id = fields.Many2one(
        'account.journal',
        string="Asset Custody Journal",
        config_parameter="nx_employee_custody_management.custody_asset_journal_id",
        help="Journal used to post the asset custody hand-over and return entries.",
    )

    custody_asset_account_id = fields.Many2one(
        'account.account',
        string="Assets Under Custody Account",
        config_parameter="nx_employee_custody_management.custody_asset_account_id",
        help="Asset account that temporarily holds the book value of the assets "
             "handed over to employees. It nets back to zero once the asset is returned.",
    )

    custody_deduction_account_id = fields.Many2one(
        'account.account',
        string="Custody Deduction Account",
        config_parameter="nx_employee_custody_management.custody_deduction_account_id",
        help="Account debited with the amount charged back to the employee when an "
             "asset is returned late, lost or damaged (e.g. employee receivable).",
    )

    custody_asset_recovery_account_id = fields.Many2one(
        'account.account',
        string="Custody Recovery Account",
        config_parameter="nx_employee_custody_management.custody_asset_recovery_account_id",
        help="Counterpart account credited with the recovered value when a "
             "deduction is charged to the employee (e.g. other income / recovery).",
    )

