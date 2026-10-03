from odoo import fields, models

HOLDING_ACCOUNT_DOMAIN = "[('reconcile', '=', True), ('account_type', 'not in', ('asset_receivable', 'liability_payable'))]"


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    check_outgoing_approval_required = fields.Boolean(
        related="company_id.check_outgoing_approval_required", readonly=False,
    )
    check_approval_segregation = fields.Boolean(
        related="company_id.check_approval_segregation", readonly=False,
    )
    check_settlement_policy = fields.Selection(
        related="company_id.check_settlement_policy", readonly=False,
    )
    check_receivable_account_id = fields.Many2one(
        related="company_id.check_receivable_account_id", readonly=False,
        domain=HOLDING_ACCOUNT_DOMAIN,
    )
    check_payable_account_id = fields.Many2one(
        related="company_id.check_payable_account_id", readonly=False,
        domain=HOLDING_ACCOUNT_DOMAIN,
    )
    check_portfolio_journal_id = fields.Many2one(
        related="company_id.check_portfolio_journal_id", readonly=False,
        domain="[('type', 'in', ('cash', 'bank')), ('company_id', '=', company_id)]",
    )
    check_advance_creates_entries = fields.Boolean(
        related="company_id.check_advance_creates_entries", readonly=False,
    )
    check_bounce_fee_policy = fields.Selection(
        related="company_id.check_bounce_fee_policy", readonly=False,
    )
    check_fee_account_id = fields.Many2one(
        related="company_id.check_fee_account_id", readonly=False,
        domain="[('account_type', 'in', ('expense', 'expense_direct_cost'))]",
    )
    check_deposit_entry = fields.Boolean(
        related="company_id.check_deposit_entry", readonly=False,
    )
    check_under_collection_account_id = fields.Many2one(
        related="company_id.check_under_collection_account_id", readonly=False,
        domain=HOLDING_ACCOUNT_DOMAIN,
    )
    check_max_redeposits = fields.Integer(
        related="company_id.check_max_redeposits", readonly=False,
    )
    check_stale_months = fields.Integer(
        related="company_id.check_stale_months", readonly=False,
    )
    check_handover_confirmation = fields.Boolean(
        related="company_id.check_handover_confirmation", readonly=False,
    )
    check_default_location_id = fields.Many2one(
        related="company_id.check_default_location_id", readonly=False,
        domain="[('company_id', '=', company_id)]",
    )
    check_reminder_due_days = fields.Integer(
        related="company_id.check_reminder_due_days", readonly=False,
    )
    check_reminder_guarantee_days = fields.Integer(
        related="company_id.check_reminder_guarantee_days", readonly=False,
    )
    check_reminder_approval_days = fields.Integer(
        related="company_id.check_reminder_approval_days", readonly=False,
    )
    check_reminder_deposit_days = fields.Integer(
        related="company_id.check_reminder_deposit_days", readonly=False,
    )
    check_discount_liability_account_id = fields.Many2one(
        related="company_id.check_discount_liability_account_id", readonly=False,
        domain=HOLDING_ACCOUNT_DOMAIN,
    )
    check_discount_cost_account_id = fields.Many2one(
        related="company_id.check_discount_cost_account_id", readonly=False,
        domain="[('account_type', 'in', ('expense', 'expense_direct_cost'))]",
    )
    check_rate_policy = fields.Selection(related="company_id.check_rate_policy", readonly=False)
    check_discount_enabled = fields.Boolean(related="company_id.check_discount_enabled", readonly=False)
    check_escalation_days = fields.Integer(related="company_id.check_escalation_days", readonly=False)
    check_horizon_short_days = fields.Integer(related="company_id.check_horizon_short_days", readonly=False)
    check_horizon_mid_days = fields.Integer(related="company_id.check_horizon_mid_days", readonly=False)
    check_horizon_long_days = fields.Integer(related="company_id.check_horizon_long_days", readonly=False)
    check_allow_manual_rate = fields.Boolean(related="company_id.check_allow_manual_rate", readonly=False)
