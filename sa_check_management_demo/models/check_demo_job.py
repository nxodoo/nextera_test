import time

from odoo import _, api, fields, models

BATCH_SIZE = 200


class CheckDemoJob(models.Model):
    """A demo data request processed in batches by a cron, one transaction per batch."""

    _name = "check.demo.job"
    _description = "Check Demo Data Job"
    _order = "id desc"

    name = fields.Char(required=True, default=lambda self: _("Demo data %s", fields.Datetime.now()))
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    requested = fields.Integer(string="Checks Requested", required=True)
    done = fields.Integer(string="Checks Created", readonly=True)
    failed = fields.Integer(string="Scenarios Failed", readonly=True)
    next_index = fields.Integer(readonly=True)
    seed = fields.Integer(default=1)
    incoming_share = fields.Integer(string="Incoming (%)", default=65)
    months_back = fields.Integer(default=12)
    months_ahead = fields.Integer(default=6)
    create_users = fields.Boolean(string="Create Demo Users", default=True)
    user_password = fields.Char(string="Demo Users Password", default="Demo@1234")
    state = fields.Selection(
        [("queued", "Queued"), ("running", "Running"), ("done", "Done")], default="queued", required=True, readonly=True,
    )
    progress = fields.Float(compute="_compute_progress")
    seconds = fields.Float(string="Seconds Spent", readonly=True)

    @api.depends("requested", "done", "failed")
    def _compute_progress(self):
        for job in self:
            job.progress = 100.0 * min(job.done + job.failed, job.requested) / job.requested if job.requested else 0.0

    @api.model
    def _first_free_index(self):
        last = self.search([], order="next_index desc", limit=1)
        return last.next_index

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("next_index", self._first_free_index())
        jobs = super().create(vals_list)
        self.env.ref("sa_check_management_demo.ir_cron_check_demo")._trigger()
        return jobs

    def _run_batch(self, size=BATCH_SIZE):
        self.ensure_one()
        started = time.time()
        remaining = self.requested - self.done - self.failed
        generator = self.env["check.demo.generator"].with_company(self.company_id)
        created, failed, next_index = generator._generate(
            min(size, remaining), seed=self.seed, start=self.next_index, incoming_share=self.incoming_share,
            months_back=self.months_back, months_ahead=self.months_ahead,
            create_users=self.create_users, password=self.user_password,
        )
        self.write({
            "done": self.done + created, "failed": self.failed + failed, "next_index": next_index,
            "seconds": self.seconds + time.time() - started,
            "state": "done" if self.done + created + self.failed + failed >= self.requested else "running",
        })

    def run_now(self):
        for job in self:
            while job.state != "done":
                job._run_batch()
        return True

    @api.model
    def _cron_process(self):
        job = self.search([("state", "!=", "done")], order="id", limit=1)
        if not job:
            self.env["ir.cron"]._notify_progress(done=0, remaining=0)
            return
        job._run_batch()
        pending = sum(j.requested - j.done - j.failed for j in self.search([("state", "!=", "done")]))
        self.env["ir.cron"]._notify_progress(done=BATCH_SIZE, remaining=pending)
