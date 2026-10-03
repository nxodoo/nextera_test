from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .check_check import CTX_ALLOW_LOCKED_EDIT

MAX_LEAVES_PER_BOOK = 1000
CTX_LEAF_SYSTEM_WRITE = "sa_check_leaf_system_write"
# Draft-side cancellations give the leaf back; anything after issue voids it.
LEAF_RELEASE_STATES = frozenset({"draft", "pending_approval", "approved"})


class AccountJournal(models.Model):
    _inherit = "account.journal"

    sa_check_require_leaf = fields.Boolean(
        string="Require Checkbook Leaves",
        help="Outgoing checks on this journal must use a leaf from a registered checkbook.",
    )


class CheckBook(models.Model):
    _name = "check.book"
    _description = "Checkbook"
    _inherit = ["mail.thread"]
    _order = "journal_id, first_number"
    _check_company_auto = True

    name = fields.Char(string="Reference", required=True, readonly=True, copy=False, default="/")
    journal_id = fields.Many2one(
        "account.journal", string="Bank", required=True, check_company=True,
        domain="[('type', '=', 'bank')]", tracking=True,
    )
    journal_require_leaf = fields.Boolean(related="journal_id.sa_check_require_leaf", readonly=False)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    generation = fields.Selection(
        selection=[("range", "Number Range"), ("list", "Imported List")],
        string="Leaves From", required=True, default="range",
        help="Generate leaves from a continuous range, or import the exact numbers of the book.",
    )
    first_number = fields.Integer(tracking=True)
    last_number = fields.Integer(tracking=True)
    padding = fields.Integer(default=6, help="Digits of the printed number; leading zeros are kept.")
    state = fields.Selection(
        selection=[("draft", "Draft"), ("active", "In Use"), ("closed", "Closed")],
        required=True, default="draft", readonly=True, copy=False, tracking=True,
    )
    leaf_ids = fields.One2many("check.book.line", "book_id", string="Leaves", readonly=True)
    leaf_count = fields.Integer(compute="_compute_counts")
    available_count = fields.Integer(compute="_compute_counts")

    @api.depends("leaf_ids.state")
    def _compute_counts(self):
        for book in self:
            book.leaf_count = len(book.leaf_ids)
            book.available_count = len(book.leaf_ids.filtered(lambda leaf: leaf.state == "available"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                company_id = vals.get("company_id") or self.env.company.id
                vals["name"] = self.env["ir.sequence"].sudo().with_company(company_id).next_by_code("sa.check.book") or "/"
        return super().create(vals_list)

    def write(self, vals):
        if {"journal_id", "first_number", "last_number", "padding"}.intersection(vals) and self.filtered(
            lambda book: book.state != "draft"
        ):
            raise UserError(_("The range of a checkbook in use cannot be changed."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if self.filtered(lambda book: book.state != "draft"):
            raise UserError(_("Only draft checkbooks can be deleted."))

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains("first_number", "last_number", "generation")
    def _check_range(self):
        for book in self.filtered(lambda b: b.generation == "range"):
            if book.first_number <= 0 or book.last_number < book.first_number:
                raise ValidationError(_("Enter a valid range: the last number must not be below the first."))
            if book.last_number - book.first_number + 1 > MAX_LEAVES_PER_BOOK:
                raise ValidationError(_("A checkbook holds at most %s leaves.", MAX_LEAVES_PER_BOOK))

    @api.constrains("journal_id", "first_number", "last_number", "generation")
    def _check_no_overlap(self):
        for book in self.filtered(lambda b: b.generation == "range"):
            overlap = self.search_count([
                ("id", "!=", book.id),
                ("generation", "=", "range"),
                ("journal_id", "=", book.journal_id.id),
                ("first_number", "<=", book.last_number),
                ("last_number", ">=", book.first_number),
            ], limit=1)
            if overlap:
                raise ValidationError(_("This range overlaps another checkbook of the same bank."))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_activate(self):
        for book in self:
            if book.state != "draft":
                raise UserError(_("Checkbook %s is already in use.", book.name))
            if book.generation == "range":
                book._generate_leaves()
            elif not book.leaf_ids:
                raise UserError(_("Import the leaf numbers of checkbook %s first.", book.name))
            super(CheckBook, book).write({"state": "active"})
            book.journal_id.sudo().sa_check_require_leaf = True
        return True

    def action_close(self):
        for book in self:
            if book.leaf_ids.filtered(lambda leaf: leaf.state == "reserved"):
                raise UserError(_("Checkbook %s has leaves reserved by draft checks.", book.name))
            unused = book.leaf_ids.filtered(lambda leaf: leaf.state == "available")
            unused._set_leaf_state("void")
            book.message_post(body=_("Closed; %s unused leaves voided.", len(unused)))
            super(CheckBook, book).write({"state": "closed"})
        return True

    def action_open_leaf_import(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Import Leaves"),
            "res_model": "check.book.import.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_book_id": self.id},
        }

    def _import_leaves(self, numbers):
        """Create leaves for these exact numbers (draft Imported List books only)."""
        self.ensure_one()
        if self.state != "draft" or self.generation != "list":
            raise UserError(_("Leaves can only be imported into a draft checkbook of type Imported List."))
        existing = set(self.env["check.book.line"].sudo().search([
            ("journal_id", "=", self.journal_id.id), ("number", "in", numbers),
        ]).mapped("number"))
        if existing:
            raise UserError(_("These numbers already exist for %(bank)s: %(numbers)s",
                              bank=self.journal_id.display_name, numbers=", ".join(sorted(existing)[:20])))
        self.env["check.book.line"].sudo().create([{"book_id": self.id, "number": number} for number in numbers])

    def _generate_leaves(self):
        self.ensure_one()
        width = max(self.padding, len(str(self.last_number)))
        self.env["check.book.line"].sudo().create([{
            "book_id": self.id,
            "number": str(number).zfill(width),
        } for number in range(self.first_number, self.last_number + 1)])


class CheckBookLine(models.Model):
    _name = "check.book.line"
    _description = "Checkbook Leaf"
    _rec_name = "number"
    _order = "journal_id, number"

    _sql_constraints = [
        ("number_unique", "UNIQUE(journal_id, number)", "This check number already exists for the bank."),
    ]

    book_id = fields.Many2one("check.book", required=True, index=True, ondelete="cascade", readonly=True)
    journal_id = fields.Many2one(related="book_id.journal_id", store=True, index=True)
    company_id = fields.Many2one(related="book_id.company_id", store=True, index=True)
    book_state = fields.Selection(related="book_id.state", string="Checkbook Status")
    number = fields.Char(required=True, readonly=True)
    state = fields.Selection(
        selection=[
            ("available", "Available"),
            ("reserved", "Reserved"),
            ("used", "Used"),
            ("void", "Void"),
            ("lost", "Lost"),
            ("damaged", "Damaged"),
        ],
        required=True, default="available", readonly=True, index=True,
    )
    check_id = fields.Many2one("check.check", string="Check", readonly=True, index="btree_not_null")
    note = fields.Text(readonly=True)

    def write(self, vals):
        if not self.env.context.get(CTX_LEAF_SYSTEM_WRITE) and not self.env.su:
            raise UserError(_("Checkbook leaves change only through check actions."))
        return super().write(vals)

    def _set_leaf_state(self, state, check=None):
        vals = {"state": state}
        if check is not None:
            vals["check_id"] = check.id if check else False
        self.sudo().with_context(**{CTX_LEAF_SYSTEM_WRITE: True}).write(vals)

    def action_mark_lost(self):
        return self._mark_unusable("lost")

    def action_mark_damaged(self):
        return self._mark_unusable("damaged")

    def _mark_unusable(self, state):
        if not self.env.user.has_group("sa_check_management.group_check_manager"):
            raise UserError(_("Only a Check Manager can mark leaves as lost or damaged."))
        if self.filtered(lambda leaf: leaf.state != "available"):
            raise UserError(_("Only available leaves can be marked lost or damaged."))
        self._set_leaf_state(state)
        for leaf in self:
            leaf.book_id.message_post(body=_("Leaf %(number)s marked %(state)s.", number=leaf.number, state=state))
        return True


class CheckCheck(models.Model):
    _inherit = "check.check"

    leaf_id = fields.Many2one(
        "check.book.line", string="Checkbook Leaf", copy=False, check_company=True,
        domain="[('journal_id', '=', journal_id), ('state', '=', 'available'), ('book_state', '=', 'active')]",
    )
    journal_requires_leaf = fields.Boolean(related="journal_id.sa_check_require_leaf")

    # ------------------------------------------------------------------
    # Leaf reservation follows the check
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._number_from_leaf(vals)
        checks = super().create(vals_list)
        for check in checks.filtered("leaf_id"):
            check._reserve_leaf(check.leaf_id)
        return checks

    def write(self, vals):
        if "leaf_id" not in vals:
            return super().write(vals)
        self._number_from_leaf(vals)
        previous = {check.id: check.leaf_id for check in self}
        result = super().write(vals)
        for check in self:
            if previous[check.id] != check.leaf_id:
                previous[check.id]._set_leaf_state("available", check=self.env["check.check"])
                if check.leaf_id:
                    check._reserve_leaf(check.leaf_id)
        return result

    @api.onchange("leaf_id")
    def _onchange_leaf_id(self):
        if self.leaf_id:
            self.check_number = self.leaf_id.number

    @api.onchange("journal_id")
    def _onchange_journal_clear_leaf(self):
        if self.leaf_id and self.leaf_id.journal_id != self.journal_id:
            self.leaf_id = False

    @api.model
    def _number_from_leaf(self, vals):
        if vals.get("leaf_id"):
            vals["check_number"] = self.env["check.book.line"].sudo().browse(vals["leaf_id"]).number

    def _reserve_leaf(self, leaf):
        self.ensure_one()
        leaf = leaf.sudo()
        if leaf.state != "available" or (leaf.check_id and leaf.check_id != self):
            raise ValidationError(_("Leaf %s is not available.", leaf.number))
        if self.check_type != "outgoing" or leaf.journal_id != self.journal_id:
            raise ValidationError(_("Leaf %s does not belong to the check's bank.", leaf.number))
        leaf._set_leaf_state("reserved", check=self)

    # ------------------------------------------------------------------
    # Transition integration
    # ------------------------------------------------------------------
    def _validate_transition(self, action):
        super()._validate_transition(action)
        if action == "issue" and self.journal_requires_leaf and not self.leaf_id:
            raise UserError(_(
                "Bank %(journal)s requires a checkbook leaf; select one before issuing.",
                journal=self.journal_id.display_name,
            ))

    def _after_transition(self, action):
        previous_state = self.event_ids.sorted("id")[-1:].old_state if self.leaf_id else False
        super()._after_transition(action)
        if not self.leaf_id:
            return
        if action == "issue":
            self.leaf_id._set_leaf_state("used", check=self)
        elif action == "lose":
            self.leaf_id._set_leaf_state("lost", check=self)
        elif action in ("cancel", "void_stale"):
            self._release_or_void_leaf(previous_state)

    def _release_or_void_leaf(self, previous_state):
        self.ensure_one()
        leaf = self.leaf_id
        if previous_state in LEAF_RELEASE_STATES:
            leaf._set_leaf_state("available", check=self.env["check.check"])
            self.with_context(**{CTX_ALLOW_LOCKED_EDIT: True}).sudo().write({"leaf_id": False})
        else:
            leaf._set_leaf_state("void", check=self)
