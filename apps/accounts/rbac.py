"""
Core RBAC resolution logic for the Waste Sales Management app.

has_page_permission() is the single source of truth for "can this user
do this action on this page" — used by BOTH the enforcement decorator
(apps/accounts/decorators.py) and the template tag
(apps/accounts/templatetags/rbac_tags.py), so the UI (which
buttons/links render) and the actual enforcement (which requests get
through) can never quietly disagree with each other.

PAGE_REGISTRY_SEED is the canonical, code-side list of every page in
the app that RBAC will eventually cover. It is the source of truth for
the sync_rbac_pages management command, which creates/updates the
PageRegistry rows and their four Django Permission objects to match —
so the database can't silently drift from what's actually in urls.py.

PHASE 1 SCOPE: every page in this app is seeded here so the full
permission matrix UI can be reviewed and role defaults set. But the
`@page_permission_required` decorator is only actually APPLIED to the
User Management views for now (see apps/accounts/views.py) — every
other page's registry entry exists so it can be planned against, but
isn't yet enforced. That rollout happens module-by-module in a later
phase, once default role permissions are reviewed and approved.
"""
from django.contrib.auth.models import Permission

# (key, label, module_group, url_name, display_order)
PAGE_REGISTRY_SEED = [
    # ── System (Phase 1: enforced now) ──
    ('user_management', 'User Management', 'System', 'accounts:user_list', 10),
    ('role_management', 'Role Management', 'System', 'accounts:role_list', 20),
    ('audit_log', 'Audit Log', 'System', 'wastage:audit_log', 30),

    # ── Master Setup (seeded, not yet enforced) ──
    ('categories', 'Categories', 'Master Setup', 'wastage:category_list', 100),
    ('items', 'Items', 'Master Setup', 'wastage:item_list', 110),
    ('departments', 'Departments', 'Master Setup', 'wastage:department_list', 120),
    ('vendors', 'Vendors', 'Master Setup', 'wastage:vendor_list', 130),
    ('group_types', 'Group Types (Masters)', 'Master Setup', 'wastage:group_type_list', 140),
    ('group_type_values', 'Group Type Values', 'Master Setup', 'wastage:generic_group_list', 150),

    # ── Stock Operations (seeded, not yet enforced) ──
    ('stock_receiving', 'Stock Receiving', 'Stock Operations', 'wastage:receiving_list', 200),
    ('monthly_stock_list', 'Stock List', 'Stock Operations', 'wastage:stock_list', 210),
    ('stock_ledger', 'Stock Ledger', 'Stock Operations', 'wastage:ledger_list', 220),
    ('item_balance', 'Item Balance', 'Stock Operations', 'wastage:balance_sheet', 230),

    # ── Sales (seeded, not yet enforced) ──
    ('quotations', 'Quotations', 'Sales', 'wastage:quotation_list', 300),
    ('quotation_comparison', 'Quotation Comparison', 'Sales', 'wastage:quotation_comparison', 310),
    ('vendor_assignments', 'Vendor Assignments', 'Sales', 'wastage:assignment_list', 320),
    ('sales_orders', 'Sales', 'Sales', 'wastage:sales_list', 330),
    ('shipments', 'Shipments', 'Sales', 'wastage:shipment_list', 340),
    ('gate_pass', 'Gate Pass', 'Sales', 'wastage:gatepass_list', 350),
    ('whatsapp_log', 'WhatsApp Log', 'Sales', 'wastage:whatsapp_list', 360),

    # ── Reports (seeded, not yet enforced) ──
    ('stock_balance_report', 'Reports', 'Reports', 'wastage:stock_balance_report', 400),
    ('monthly_stock_report', 'Monthly Stock Report', 'Reports', 'wastage:monthly_stock_report', 410),
]


def has_page_permission(user, page_key, action='view'):
    """Effective permission for (user, page_key, action):

    1. Not authenticated -> always False.
    2. Superuser -> always True (Django convention; also our own
       'admin' role should be made superuser or given every
       permission directly — see the role default proposal).
    3. An explicit UserPagePermissionOverride, if one exists for this
       exact (user, page, action) -> its grant value wins outright,
       in EITHER direction (grant beyond role, or deny despite role).
    4. Otherwise -> whatever the user's role(s)/Group(s) grant, via
       Django's own has_perm().
    5. An unregistered or inactive page -> fails CLOSED (False), not
       open — a page that isn't in the registry yet should never be
       silently treated as accessible.
    """
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True

    # Local import avoids a hard circular-import dependency between
    # models.py and this module at Django app-loading time.
    from .models import PageRegistry, UserPagePermissionOverride

    try:
        page = PageRegistry.objects.get(key=page_key, is_active=True)
    except PageRegistry.DoesNotExist:
        return False

    override = UserPagePermissionOverride.objects.filter(user=user, page=page, action=action).first()
    if override is not None:
        return override.grant

    return user.has_perm(f'accounts.{page.codename(action)}')


def sync_permissions_for_page(page):
    """Ensures the Django Permission objects for every action that
    genuinely applies to this page (see PageRegistry.action_applies)
    exist, attached to the shared PagePermissionAnchor content type.
    Called by sync_rbac_pages for every seeded page; safe to call
    repeatedly (get_or_create). 'cancel' is only ever created for
    Gate Pass -- every other page skips it, rather than getting an
    unused permission object cluttering the list."""
    from django.contrib.contenttypes.models import ContentType
    from .models import PagePermissionAnchor

    content_type = ContentType.objects.get_for_model(PagePermissionAnchor)
    created_count = 0
    for action in page.ACTIONS:
        if not page.action_applies(action):
            continue
        _, created = Permission.objects.get_or_create(
            codename=page.codename(action),
            content_type=content_type,
            defaults={'name': f'Can {action} {page.label}'},
        )
        if created:
            created_count += 1
    return created_count
