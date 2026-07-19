from . import models
from . import wizard


def post_init_hook(env):
    """Create KPI rules and relax payroll input-type multi-company filtering."""
    env["hr.payslip"]._sync_kpi_rules_to_structures()
    env.ref("hr_payroll.ir_rule_hr_payslip_input_type_multi_company").write(
        {"domain_force": "[(1, '=', 1)]"}
    )
