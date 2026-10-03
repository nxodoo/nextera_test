import logging

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Prepare check accounts and the portfolio journal for companies that already have a chart."""
    for company in env["res.company"].search([("chart_template", "!=", False)]):
        try:
            company._sa_check_accounting_setup()
        except UserError as exc:
            _logger.warning("Check accounting setup skipped for %s: %s", company.name, exc)
