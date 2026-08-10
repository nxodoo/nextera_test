# -*- coding: utf-8 -*-
from . import models


def post_init_hook(env):
    """Generate the required-document checklist for employees that already
    exist when the module is installed/updated."""
    env["hr.employee"].with_context(active_test=False).search(
        [])._sync_required_documents()
