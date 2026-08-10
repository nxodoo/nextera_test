# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class NxHrDashboardService(models.AbstractModel):
    """Backend aggregation service for the HR Analytics Dashboard.

    All figures come from real records via ``read_group``/``search_count`` and
    respect the current user's access rights (no sudo). Optional feature
    modules (social insurance, payroll tax) are integrated defensively so the
    dashboard works even when they are not installed.
    """
    _name = "nx.hr.dashboard.service"
    _description = "HR Analytics Dashboard Service"

    # ── Helpers ────────────────────────────────────────────────────────────
    def _employee_domain(self, filters):
        domain = []
        if filters.get("department_id"):
            domain.append(("department_id", "=", int(filters["department_id"])))
        if filters.get("company_id"):
            domain.append(("company_id", "=", int(filters["company_id"])))
        return domain

    def _has_model(self, model):
        return model in self.env

    # ── Public entry point ─────────────────────────────────────────────────
    @api.model
    def get_dashboard_data(self, filters=None):
        filters = filters or {}
        return {
            "kpis": self._get_kpis(filters),
            "currency": self.env.company.currency_id.name,
            "headcount_by_department": self._headcount_by_department(filters),
            "top_paid_positions": self._top_paid_positions(filters),
            "social_insurance": self._social_insurance_status(filters),
            "headcount_trend": self._headcount_trend(filters),
            "document_compliance": self._document_compliance(filters),
            "turnover_trend": self._turnover_trend(filters),
            "payroll_tax": self._payroll_tax_summary(filters),
            "alerts": self._alerts(filters),
            "filter_options": self._filter_options(),
        }

    # ── Filter options ───────────────────────────────────────────────────
    @api.model
    def _filter_options(self):
        departments = self.env["hr.department"].search_read([], ["name"])
        companies = self.env["res.company"].search_read(
            [("id", "in", self.env.companies.ids)], ["name"])
        return {
            "departments": [{"id": d["id"], "name": d["name"]} for d in departments],
            "companies": [{"id": c["id"], "name": c["name"]} for c in companies],
        }

    # ── KPI cards ────────────────────────────────────────────────────────
    def _get_kpis(self, filters):
        Employee = self.env["hr.employee"]
        domain = self._employee_domain(filters)
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)

        total = Employee.search_count(domain)
        active = Employee.search_count(domain + [("active", "=", True)])

        new_hires = Employee.search_count(
            domain + [("create_date", ">=", fields.Datetime.to_string(
                fields.Datetime.now().replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0)))])

        resignations = Employee.with_context(active_test=False).search_count(
            domain + [("departure_date", ">=", month_start),
                      ("departure_date", "<=", today)])

        uninsured = self._uninsured_count(filters)
        missing_docs = 0
        if self._has_model("hr.employee.document"):
            missing_docs = self.env["hr.employee.document"].search_count(
                [("state", "=", "missing"), ("mandatory", "=", True)]
                + self._doc_employee_domain(filters))

        return {
            "total_employees": total,
            "active_employees": active,
            "new_hires": new_hires,
            "resignations": resignations,
            "uninsured": uninsured,
            "missing_documents": missing_docs,
            "net_change": new_hires - resignations,
        }

    def _doc_employee_domain(self, filters):
        domain = []
        if filters.get("department_id"):
            domain.append(("employee_id.department_id", "=", int(filters["department_id"])))
        if filters.get("company_id"):
            domain.append(("company_id", "=", int(filters["company_id"])))
        return domain

    # ── Headcount by department ─────────────────────────────────────────
    def _headcount_by_department(self, filters):
        domain = self._employee_domain(filters) + [("active", "=", True)]
        groups = self.env["hr.employee"].read_group(
            domain, ["department_id"], ["department_id"], orderby="__count desc")
        return [{
            "id": g["department_id"][0] if g["department_id"] else False,
            "label": g["department_id"][1] if g["department_id"] else "Undefined",
            "value": g["department_id_count"] if "department_id_count" in g else g["__count"],
        } for g in groups]

    # ── Top paid job positions ───────────────────────────────────────────
    def _top_paid_positions(self, filters, limit=6):
        """Average wage and contract count per job position (running contracts)."""
        if "hr.contract" not in self.env:
            return []
        domain = [("state", "=", "open")]
        if filters.get("company_id"):
            domain.append(("company_id", "=", int(filters["company_id"])))
        if filters.get("department_id"):
            domain.append(("department_id", "=", int(filters["department_id"])))
        try:
            groups = self.env["hr.contract"].read_group(
                domain, ["wage:avg"], ["job_id"])
        except AccessError:
            return []
        rows = []
        for g in groups:
            if not g.get("job_id"):
                continue
            rows.append({
                "id": g["job_id"][0],
                "label": g["job_id"][1],
                "contracts": g.get("job_id_count", g.get("__count", 0)),
                "avg_salary": round(g.get("wage") or 0.0, 2),
            })
        rows.sort(key=lambda r: r["avg_salary"], reverse=True)
        return rows[:limit]

    # ── Social insurance status ──────────────────────────────────────────
    INSURANCE_FIELD = "l10n_eg_social_insurance_reference"

    def _insurance_field(self):
        """Return the contract insurance-reference field name if available."""
        if "hr.contract" not in self.env:
            return None
        if self.INSURANCE_FIELD not in self.env["hr.contract"]._fields:
            return None
        return self.INSURANCE_FIELD

    def _social_insurance_status(self, filters):
        """Insured/Not-Insured based on the employee's current contract.

        An employee is Insured when their running contract's
        ``l10n_eg_social_insurance_reference`` (Social Insurance Reference
        Amount) is greater than zero; otherwise Not Insured.
        """
        field = self._insurance_field()
        if not field:
            return None
        Employee = self.env["hr.employee"]
        base = self._employee_domain(filters) + [("active", "=", True)]
        total = Employee.search_count(base)
        insured = Employee.search_count(base + [("contract_id." + field, ">", 0)])
        return {"insured": insured, "not_insured": total - insured}

    def _uninsured_count(self, filters):
        status = self._social_insurance_status(filters)
        if status is None:
            return 0
        return status["not_insured"]

    # ── Headcount trend (last 12 months) ─────────────────────────────────
    def _headcount_trend(self, filters):
        Employee = self.env["hr.employee"].with_context(active_test=False)
        base_domain = self._employee_domain(filters)
        today = fields.Date.context_today(self)
        labels, values = [], []
        for i in range(11, -1, -1):
            month_end = (today.replace(day=1) - relativedelta(months=i)
                         + relativedelta(months=1) - relativedelta(days=1))
            count = Employee.search_count(base_domain + [
                ("create_date", "<=", fields.Datetime.to_string(
                    fields.Datetime.to_datetime(str(month_end)).replace(
                        hour=23, minute=59, second=59))),
                "|", ("departure_date", "=", False),
                ("departure_date", ">", month_end),
            ])
            labels.append(month_end.strftime("%b %y"))
            values.append(count)
        return {"labels": labels, "values": values}

    # ── Document compliance ──────────────────────────────────────────────
    def _document_compliance(self, filters):
        if not self._has_model("hr.employee.document"):
            return None
        Employee = self.env["hr.employee"]
        emps = Employee.search(self._employee_domain(filters) + [("active", "=", True)])
        complete = incomplete = expired = 0
        for emp in emps:
            status = emp.document_status
            if status == "expired":
                expired += 1
            elif status == "incomplete":
                incomplete += 1
            else:
                complete += 1
        return {"complete": complete, "incomplete": incomplete, "expired": expired}

    # ── Turnover trend (%) ───────────────────────────────────────────────
    def _turnover_trend(self, filters):
        Employee = self.env["hr.employee"].with_context(active_test=False)
        base_domain = self._employee_domain(filters)
        today = fields.Date.context_today(self)
        labels, values = [], []
        for i in range(11, -1, -1):
            first = today.replace(day=1) - relativedelta(months=i)
            last = first + relativedelta(months=1) - relativedelta(days=1)
            departures = Employee.search_count(base_domain + [
                ("departure_date", ">=", first),
                ("departure_date", "<=", last),
            ])
            headcount = Employee.search_count(base_domain + [
                ("create_date", "<=", fields.Datetime.to_string(
                    fields.Datetime.to_datetime(str(last)).replace(
                        hour=23, minute=59, second=59))),
                "|", ("departure_date", "=", False),
                ("departure_date", ">", last),
            ]) or 1
            rate = round((departures / headcount) * 100.0, 2)
            labels.append(first.strftime("%b %y"))
            values.append(rate)
        return {"labels": labels, "values": values}

    # ── Payroll tax summary ──────────────────────────────────────────────
    def _payroll_tax_summary(self, filters):
        if not self._has_model("nx.egypt.payroll.tax"):
            return None
        configs = self.env["nx.egypt.payroll.tax"].search(
            [("state", "=", "active")], order="effective_date desc")
        if not configs:
            return None
        name = (configs.name if len(configs) == 1
                else _("Egypt Payroll Tax · %s active brackets") % len(configs))
        return {
            "name": name,
            "total_employees": self.env["hr.employee"].search_count(
                self._employee_domain(filters) + [("active", "=", True)]),
            "action": "nx.egypt.payroll.tax",
        }

    # ── Payroll Tax tab (per-employee monthly breakdown) ────────────────
    @api.model
    def get_payroll_tax_data(self, filters=None):
        """Per-employee payroll-tax breakdown for a month.

        Uses the past month's payslips when available (real payroll), and
        otherwise projects the figures from each active employee's contract
        wage through the Egypt payroll-tax engine so the tab is still useful
        before payslips are posted.
        """
        filters = filters or {}
        today = fields.Date.context_today(self)
        # Target month: explicit 'YYYY-MM' filter, else the previous month.
        if filters.get("month"):
            year, month = (int(x) for x in filters["month"].split("-"))
            month_start = today.replace(year=year, month=month, day=1)
        else:
            month_start = today.replace(day=1) - relativedelta(months=1)
        month_end = month_start + relativedelta(months=1) - relativedelta(days=1)

        tax_config = None
        exemption_annual = 0.0
        active_count = 0
        if self._has_model("nx.egypt.payroll.tax"):
            configs = self.env["nx.egypt.payroll.tax"].search(
                [("state", "=", "active")], order="effective_date desc")
            active_count = len(configs)
            tax_config = configs[:1]
            if tax_config:
                exemption_annual = tax_config.total_exemption_limit or 0.0
        exemption_month = exemption_annual / 12.0

        # The active tax scheme is a SET of net-income brackets (one record per
        # category); the engine picks the matching bracket per employee. Show
        # the whole scheme rather than one arbitrary bracket name.
        if active_count == 0:
            config_name = None
        elif active_count == 1:
            config_name = tax_config.name
        else:
            config_name = _("Egypt Payroll Tax · %s active brackets") % active_count

        rows, source = self._payroll_rows_from_payslips(
            filters, month_start, month_end, exemption_month)
        if not rows:
            rows = self._payroll_rows_projected(filters, exemption_month)
            source = "projected"

        totals = {
            "employees": len(rows),
            "gross": sum(r["gross"] for r in rows),
            "insurance": sum(r["insurance"] for r in rows),
            "exemptions": sum(r["exemptions"] for r in rows),
            "deductions": sum(r["deductions"] for r in rows),
            "taxable_base": sum(r["taxable_base"] for r in rows),
            "tax_due": sum(r["tax_due"] for r in rows),
            "net": sum(r["net"] for r in rows),
        }
        totals["tax_ratio"] = round(
            (totals["tax_due"] / totals["gross"] * 100.0) if totals["gross"] else 0.0, 1)

        filing_deadline = month_end + relativedelta(days=15)
        return {
            "month_label": month_start.strftime("%B %Y"),
            "month_value": month_start.strftime("%Y-%m"),
            "source": source,
            "config_name": config_name,
            "active_brackets": active_count,
            "exemption": round(exemption_annual, 2),
            "currency": (tax_config.currency_id.name if tax_config
                         else self.env.company.currency_id.name),
            "filing_deadline": filing_deadline.strftime("%d/%m/%Y"),
            "prepared_by": self.env.user.name,
            "rows": rows,
            "totals": totals,
            "month_options": self._payroll_month_options(today),
            "filter_options": self._filter_options(),
        }

    def _payroll_month_options(self, today):
        opts = []
        for i in range(0, 12):
            d = today.replace(day=1) - relativedelta(months=i)
            opts.append({"value": d.strftime("%Y-%m"), "label": d.strftime("%B %Y")})
        return opts

    def _emp_code(self, employee):
        return employee.barcode or ("EMP-%03d" % employee.id)

    def _payslip_status(self, payslip):
        return {
            "paid": "approved", "done": "reviewed", "verify": "waiting",
            "draft": "draft", "cancel": "cancelled",
        }.get(payslip.state, "draft")

    def _payroll_rows_from_payslips(self, filters, month_start, month_end, exemption_month):
        if not self._has_model("hr.payslip"):
            return [], "payslip"
        domain = [
            ("date_from", "<=", month_end),
            ("date_to", ">=", month_start),
            ("state", "!=", "cancel"),
        ]
        if filters.get("company_id"):
            domain.append(("company_id", "=", int(filters["company_id"])))
        if filters.get("department_id"):
            domain.append(("employee_id.department_id", "=", int(filters["department_id"])))
        try:
            payslips = self.env["hr.payslip"].search(domain)
        except AccessError:
            return [], "payslip"
        rows = []
        for slip in payslips:
            emp = slip.employee_id
            totals = {}
            insurance = 0.0
            ded_total = 0.0
            tax = 0.0
            for line in slip.line_ids:
                mag = abs(line.total)
                code = (line.code or "").upper()
                name = (line.name or "").lower()
                if code == "EGY_TAX":
                    tax = mag
                if line.category_id and line.category_id.code == "DED":
                    ded_total += mag
                if code in ("INS", "INSURANCE", "SI") or "insurance" in name:
                    insurance += mag
                totals[code] = line.total
            gross = slip.gross_wage or abs(totals.get("GROSS", 0.0))
            other_ded = max(0.0, ded_total - tax - insurance)
            taxable_base = max(0.0, gross - exemption_month - insurance - other_ded)
            # Red "error" only for genuine calculation problems; a missing
            # national ID is a softer "warning".
            if gross <= 0:
                status, note = "error", "Calculation discrepancy"
            elif not emp.identification_id:
                status, note = "warning", "Missing national ID"
            else:
                status, note = self._payslip_status(slip), ""
            rows.append({
                "code": self._emp_code(emp),
                "name": emp.name,
                "national_id": emp.identification_id or "---",
                "department": emp.department_id.name or "",
                "job": emp.job_id.name or "",
                "gross": round(gross, 2),
                "insurance": round(insurance, 2),
                "exemptions": round(exemption_month, 2),
                "deductions": round(other_ded, 2),
                "taxable_base": round(taxable_base, 2),
                "tax_due": round(tax, 2),
                "net": round(slip.net_wage or (gross - tax - insurance - other_ded), 2),
                "status": status,
                "note": note,
            })
        return rows, "payslip"

    def _payroll_rows_projected(self, filters, exemption_month):
        Employee = self.env["hr.employee"]
        emps = Employee.search(self._employee_domain(filters) + [("active", "=", True)])
        engine = (self.env["nx.egypt.payroll.tax"]
                  if self._has_model("nx.egypt.payroll.tax") else None)
        rows = []
        for emp in emps:
            contract = getattr(emp, "contract_id", False)
            gross = contract.wage if contract else 0.0
            if not gross:
                continue
            tax = engine.compute_employee_monthly_tax(gross) if engine else 0.0
            # Estimate the employee social-insurance contribution (~11% of the
            # contract's Social Insurance Reference Amount) when available.
            insurance = 0.0
            ins_field = self._insurance_field()
            if contract and ins_field:
                ref = getattr(contract, ins_field, 0.0) or 0.0
                insurance = round(ref * 0.11, 2)
            taxable_base = max(0.0, gross - exemption_month - insurance)
            if not emp.identification_id:
                status, note = "warning", "Missing national ID · projected"
            else:
                status, note = "draft", "Projected from contract"
            rows.append({
                "code": self._emp_code(emp),
                "name": emp.name,
                "national_id": emp.identification_id or "---",
                "department": emp.department_id.name or "",
                "job": emp.job_id.name or "",
                "gross": round(gross, 2),
                "insurance": round(insurance, 2),
                "exemptions": round(exemption_month, 2),
                "deductions": 0.0,
                "taxable_base": round(taxable_base, 2),
                "tax_due": round(tax, 2),
                "net": round(gross - tax - insurance, 2),
                "status": status,
                "note": note,
            })
        return rows

    # ── Documents tab ────────────────────────────────────────────────────
    @api.model
    def get_documents_data(self, filters=None):
        filters = filters or {}
        if not self._has_model("hr.employee.document"):
            return None
        Employee = self.env["hr.employee"]
        Document = self.env["hr.employee.document"]
        emps = Employee.search(self._employee_domain(filters) + [("active", "=", True)])
        doc_domain = [("mandatory", "=", True)] + self._doc_employee_domain(filters)

        complete = len(emps.filtered(lambda e: e.document_status == "complete"))
        incomplete = len(emps.filtered(lambda e: e.document_status == "incomplete"))
        expired_emp = len(emps.filtered(lambda e: e.document_status == "expired"))

        kpis = {
            "total_employees": len(emps),
            "complete_files": complete,
            "incomplete_files": incomplete + expired_emp,
            "missing_documents": Document.search_count(
                doc_domain + [("state", "=", "missing")]),
            "expired_documents": Document.search_count(
                doc_domain + [("state", "=", "expired")]),
            "expiring_soon": Document.search_count(
                doc_domain + [("state", "=", "expiring")]),
        }

        # Missing documents by type (horizontal bar).
        groups = Document.read_group(
            doc_domain + [("state", "=", "missing")],
            ["document_type_id"], ["document_type_id"], orderby="__count desc")
        by_type = [{
            "label": g["document_type_id"][1] if g["document_type_id"] else "Other",
            "value": g.get("document_type_id_count", g.get("__count", 0)),
        } for g in groups]

        rows = [{
            "id": e.id,
            "code": self._emp_code(e),
            "name": e.name,
            "department": e.department_id.name or "",
            "job": e.job_id.name or "",
            "required": e.document_required_count,
            "complete": e.document_complete_count,
            "missing": e.document_missing_count,
            "expired": e.document_expired_count,
            "pct": round(e.document_compliance_rate),
            "status": e.document_status or "complete",
        } for e in emps]

        return {
            "kpis": kpis,
            "compliance": {"complete": complete, "incomplete": incomplete, "expired": expired_emp},
            "missing_by_type": by_type,
            "rows": rows,
            "filter_options": self._filter_options(),
        }

    # ── Insurance tab ────────────────────────────────────────────────────
    @api.model
    def get_insurance_data(self, filters=None):
        """Social-insurance overview driven by the contract reference amount.

        Insured  = current contract's Social Insurance Reference Amount > 0.
        """
        filters = filters or {}
        field = self._insurance_field()
        if not field:
            return None
        Employee = self.env["hr.employee"]
        emps = Employee.search(self._employee_domain(filters) + [("active", "=", True)])

        insured = not_insured = no_contract = 0
        total_ref = 0.0
        rows = []
        by_dept_insured = {}
        for emp in emps:
            contract = emp.contract_id if "contract_id" in emp._fields else False
            amount = 0.0
            start = ""
            basic = 0.0
            if contract:
                amount = getattr(contract, field, 0.0) or 0.0
                basic = contract.wage or 0.0
                start = contract.date_start.strftime("%d/%m/%Y") if contract.date_start else ""
            else:
                no_contract += 1
            is_insured = amount > 0
            if is_insured:
                insured += 1
                total_ref += amount
                dept = emp.department_id.name or "Undefined"
                by_dept_insured[dept] = by_dept_insured.get(dept, 0) + 1
            else:
                not_insured += 1
            rows.append({
                "id": emp.id,
                "code": self._emp_code(emp),
                "name": emp.name,
                "national_id": emp.identification_id or "---",
                "department": emp.department_id.name or "",
                "job": emp.job_id.name or "",
                "contract_start": start or "---",
                "basic_wage": round(basic, 2),
                "reference_amount": round(amount, 2),
                "status": "insured" if is_insured else "not_insured",
            })

        total = len(emps)
        coverage = round((insured / total) * 100.0, 1) if total else 0.0
        by_dept = sorted(
            [{"label": k, "value": v} for k, v in by_dept_insured.items()],
            key=lambda d: d["value"], reverse=True)

        return {
            "kpis": {
                "total_employees": total,
                "insured": insured,
                "not_insured": not_insured,
                "coverage": coverage,
                "total_reference": round(total_ref, 2),
                "no_contract": no_contract,
            },
            "status": {"insured": insured, "not_insured": not_insured},
            "by_department": by_dept,
            "currency": self.env.company.currency_id.name,
            "rows": rows,
            "filter_options": self._filter_options(),
        }

    # ── Alerts & required actions ────────────────────────────────────────
    def _alerts(self, filters):
        alerts = []
        today = fields.Date.context_today(self)

        status = self._social_insurance_status(filters)
        if status and status["not_insured"]:
            alerts.append({
                "type": "danger",
                "title": "%s Employees Not Enrolled in Insurance" % status["not_insured"],
                "subtitle": "No active social insurance coverage",
                "action_label": "View Employee List",
                "action": "employees_uninsured",
            })

        if self._has_model("hr.employee.document"):
            incomplete_emps = len(self.env["hr.employee"].search(
                self._employee_domain(filters) + [("active", "=", True),
                                                   ("document_status", "=", "incomplete")]))
            if incomplete_emps:
                alerts.append({
                    "type": "warning",
                    "title": "%s Employees with Incomplete Documents" % incomplete_emps,
                    "subtitle": "Files require completion",
                    "action_label": "View Document Report",
                    "action": "documents_incomplete",
                })
            expiring = self.env["hr.employee.document"].search_count(
                [("state", "in", ("expiring", "expired"))]
                + self._doc_employee_domain(filters))
            if expiring:
                alerts.append({
                    "type": "warning",
                    "title": "%s Documents Expired or Expiring Soon" % expiring,
                    "subtitle": "Action required within 30 days",
                    "action_label": "View Details",
                    "action": "documents_expiring",
                })

        payroll = self._payroll_tax_summary(filters)
        if payroll:
            alerts.append({
                "type": "info",
                "title": "Payroll Tax Configuration Active",
                "subtitle": payroll["name"],
                "action_label": "Review",
                "action": "payroll_tax",
            })

        return alerts
