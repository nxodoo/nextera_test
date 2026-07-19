from . import models

def post_init_hook(env):
    """Create the unpaid expense deduction rule on existing payroll structures."""
    env["hr.payslip"]._sync_unpaid_expense_rules_to_structures()
