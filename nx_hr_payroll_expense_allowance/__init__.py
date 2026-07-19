from . import models


def post_init_hook(env):
    """Attach default payslip input to companies and replicate the EXP rule on structures."""
    input_type = env.ref(
        "nx_hr_payroll_expense_allowance.hr_payslip_input_type_expense_allowance",
        raise_if_not_found=False,
    )
    if input_type:
        env["res.company"].search([("payroll_expense_allowance_input_type_id", "=", False)]).write(
            {"payroll_expense_allowance_input_type_id": input_type.id}
        )
    env["hr.payslip"]._sync_expense_allowance_rules_to_structures()
