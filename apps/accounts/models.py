from django.contrib.auth.models import AbstractUser
from django.db import models

class Division(models.Model):
    """Real reference table for divisions, replacing the previously-
    hardcoded DIVISION_CHOICES list as the source of truth going
    forward. Seeded from that exact list by the backfill_user_divisions
    management command -- see its docstring for the full migration
    sequence this is Step 1 of.

    CustomUser.division (the legacy single CharField, still present
    below) is left completely untouched for now and keeps working
    exactly as it always has -- nothing yet reads from this model or
    from CustomUser.divisions below. This is deliberately isolated:
    schema first, verified on its own, before any view or query
    changes what it actually reads."""
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    display_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'name']
        verbose_name_plural = "Divisions"

    def __str__(self):
        return self.name


class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'Administrator'),
        ('manager', 'Manager'),
        ('hr', 'HR Officer'),
        ('payroll', 'Payroll Officer'),
        ('viewer', 'Viewer'),
    ]
    DIVISION_CHOICES = [
        ('08', 'Soorty Denim (Landhi)'),
        ('11', 'Soorty Spinning'),
        ('13', 'Soorty Denim (Nooriabad)'),
        ('16', 'Soorty Sewing Thread'),
        ('19', 'Soorty Spinning (Nooriabad)'),
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='viewer')
    division = models.CharField(
        max_length=20, choices=DIVISION_CHOICES, default='08',
        help_text='LEGACY single-division field -- being phased out in favor of '
                   'the `divisions` (plural) many-to-many field below. Every '
                   'fetch function in oracle_data.py still reads this one; it '
                   'stays authoritative and untouched until each module is '
                   'individually migrated to `divisions` instead. Kept in sync '
                   'with `divisions` by user_create/user_edit during the '
                   'transition (see accounts/views.py).'
    )
    divisions = models.ManyToManyField(
        Division, related_name='users', blank=True,
        help_text='Multi-division access -- the actual set of divisions this '
                   'user can see/act in, going forward. Independent of '
                   'sees_all_divisions (which bypasses both this and `division` '
                   'entirely). Not yet read by any oracle_data.py query -- see '
                   'Division\'s own docstring for why this is deliberately '
                   'introduced before anything consumes it.'
    )
    sees_all_divisions = models.BooleanField(
        default=False,
        help_text='Grants cross-division visibility (view, edit, delete across ALL divisions, '
                   'and choose the division when creating records). Independent of role — '
                   'grant this only to specific trusted users/admins who genuinely need it.'
    )
    department = models.CharField(max_length=100, blank=True)
    employee_id = models.CharField(max_length=20, blank=True, unique=True, null=True)
    phone = models.CharField(max_length=20, blank=True)
    datatex_user_id = models.CharField(
        max_length=50, blank=True, null=True, unique=True,
        help_text='Maps this local account to its ID_ row in the centralized '
                   'ACT_ID_USER_VW view. Leave blank for local-only accounts '
                   '(e.g. Django superusers) -- CustomDatatexAuthBackend uses '
                   'the presence of this field, not is_superuser directly, to '
                   'decide whether a login attempt is checked against the '
                   'centralized view or against the local Django password.'
    )

    def __str__(self):
        return f"{self.get_full_name()} ({self.role})"


# ═══════════════════════════════════════════════════════════════════
# RBAC — Page/Action-level permissions
#
# Roles reuse Django's built-in Group model (Group.permissions), and
# user-to-role reuses Django's built-in User.groups — no new tables for
# either. The two models below cover what Django doesn't provide out of
# the box: a registry of this app's pages (which aren't Django ORM
# models, so there's nothing for Django to auto-generate per-page
# permissions against), and a per-user override layer that can both
# grant beyond a role AND deny something a role would otherwise grant
# (Django's stock Permission model is additive-only).
# ═══════════════════════════════════════════════════════════════════

class PagePermissionAnchor(models.Model):
    """Exists purely to give Django's Permission system a ContentType to
    attach dynamically-generated page/action permissions to. This app's
    pages are Django views over raw-SQL Oracle data, not ORM models, so
    there's no natural model for Django to auto-generate add/change/
    delete/view permissions against the way it normally would. This
    anchor is that attachment point — it is never queried, instantiated,
    or given a database row of its own significance. default_permissions
    is set to () so Django doesn't also auto-create its own generic
    add/change/delete/view permissions for the anchor itself, which
    would otherwise clutter the permission list with entries that mean
    nothing for this model specifically."""
    class Meta:
        managed = True
        default_permissions = ()
        verbose_name = "Page Permission Anchor"
        verbose_name_plural = "Page Permission Anchor"


class PageRegistry(models.Model):
    """The canonical list of permission-checkable pages/forms in the
    app. Seeded and kept in sync with the codebase via the
    sync_rbac_pages management command (see apps/accounts/management/
    commands/sync_rbac_pages.py) rather than maintained by hand, so it
    can't silently drift from what actually exists in urls.py."""
    key = models.SlugField(max_length=100, unique=True)
    label = models.CharField(max_length=150)
    module_group = models.CharField(max_length=100, help_text='Groups pages into sections in the permission matrix UI, e.g. "Sales", "Master Setup", "System".')
    url_name = models.CharField(max_length=150, blank=True, help_text='Primary Django URL name for reference, e.g. "wastage:sales_list". Informational — the enforcement decorator is applied explicitly per view, not derived from this field.')
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True, help_text='Soft-disable a page from the matrix UI without losing historical permission/override records tied to it.')

    ACTIONS = ['view', 'create', 'edit', 'delete', 'cancel', 'manual_gp_no']

    class Meta:
        ordering = ['module_group', 'display_order', 'label']
        verbose_name_plural = "Page Registry"

    def __str__(self):
        return self.label

    def codename(self, action):
        """The Django Permission codename for this page's given action,
        e.g. codename('create') -> 'create_page_sales_orders'."""
        return f'{action}_page_{self.key}'

    def action_applies(self, action):
        """Whether `action` is genuinely meaningful for THIS page, as
        opposed to merely being one of the actions the system supports
        in general (ACTIONS is shared across every page). Every page
        supports the base four; 'cancel' and 'manual_gp_no' are both
        scoped to Gate Pass only, since that's the only page anything
        actually enforces either of them against (see gatepass_cancel()
        and gatepass_set_manual_no() in apps/wastage/views.py).
        Kept as a single, explicit method rather than a per-row
        database field -- the scope here is narrow and known ahead of
        time, so a real schema column would be more machinery than the
        actual requirement calls for."""
        if action in ('cancel', 'manual_gp_no'):
            return self.key == 'gate_pass'
        return True


class UserPagePermissionOverride(models.Model):
    """Per-user, per-page, per-action override sitting on top of a
    user's role-derived (Group) permissions. grant=True explicitly
    grants this action regardless of role; grant=False explicitly
    denies it regardless of role — covering the "revoke Delete for this
    one person without creating a whole new role" case Django's stock
    Permission model can't express on its own."""
    ACTION_CHOICES = [
        ('view', 'View'),
        ('create', 'Create'),
        ('edit', 'Edit'),
        ('delete', 'Delete'),
        ('cancel', 'Cancel'),
        ('manual_gp_no', 'Manual Gate Pass No.'),
    ]
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='page_permission_overrides')
    page = models.ForeignKey(PageRegistry, on_delete=models.CASCADE, related_name='user_overrides')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    grant = models.BooleanField(help_text='True = explicitly grant this action regardless of role. False = explicitly deny it regardless of role.')
    granted_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    granted_date = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'page', 'action'], name='unique_user_page_action_override')
        ]
        verbose_name = "User Permission Override"

    def __str__(self):
        return f"{self.user.username}: {'GRANT' if self.grant else 'DENY'} {self.action} on {self.page.label}"