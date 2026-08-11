# -*- coding: utf-8 -*-

from odoo import fields, models


class AccountJournal(models.Model):
    """ Extend account.journal to flag journals usable for custody payments. """

    _inherit = "account.journal"

    is_custody = fields.Boolean(
        string="Is Custody",
        help="Enable this so the journal (and its account) can be used "
             "when paying from custody.",
    )
