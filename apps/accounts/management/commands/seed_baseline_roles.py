"""
python manage.py seed_baseline_roles

Creates five baseline Groups (Administrator, Manager, HR Officer,
Payroll Officer, Viewer) and grants each a starting set of page
permissions -- NOT empty, deliberately. The whole point of applying
@page_permission_required across every remaining page in the same
rollout as this command is that enforcement goes live everywhere at
once; if these roles started with zero permissions, every account
mapped into them would be locked out of the entire app the moment that
happens, which is the opposite of what was asked for ("no active
account gets locked out").

These starting grants are a safety net, not a policy recommendation --
running this command doesn't require accepting any particular access
philosophy. Everything here is fully editable from the Role Management
screen immediately after this runs, per the explicit request to manage
all of this dynamically from the UI rather than through a fixed
definition.

Safe to run repeatedly: existing Groups and their permissions are left
untouched (get_or_create), so re-running this after you've already
started customizing a role in the UI won't overwrite your changes.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from apps.accounts.rbac import PAGE_REGISTRY_SEED


class Command(BaseCommand):
    help = "Create baseline Roles (Groups) with non-empty starting permissions."

    def handle(self, *args, **options):
        from apps.accounts.models import PageRegistry, PagePermissionAnchor

        pages = {p.key: p for p in PageRegistry.objects.filter(is_active=True)}
        content_type = ContentType.objects.get_for_model(PagePermissionAnchor)
        permissions = {p.codename: p for p in Permission.objects.filter(content_type=content_type)}

        def grant(group, page_key, actions):
            page = pages.get(page_key)
            if not page:
                return
            for action in actions:
                codename = page.codename(action)
                perm = permissions.get(codename)
                if perm:
                    group.permissions.add(perm)

        # ── Administrator: everything ──
        admin_group, created = Group.objects.get_or_create(name='Administrator')
        if created:
            for key in pages:
                grant(admin_group, key, ['view', 'create', 'edit', 'delete'])
            self.stdout.write(self.style.SUCCESS('Created "Administrator" -- full access to all pages.'))
        else:
            self.stdout.write('Skip "Administrator" (already exists) -- left untouched.')

        # ── Manager: broad operational access, System stays admin-only
        #    except read-only Audit Log oversight. Delete withheld except
        #    on Shipments/Gate Pass, which use cancellation rather than a
        #    literal delete. ──
        manager_group, created = Group.objects.get_or_create(name='Manager')
        if created:
            grant(manager_group, 'audit_log', ['view'])
            operational_pages = [key for key, label, module_group, url_name, order in PAGE_REGISTRY_SEED
                                  if module_group in ('Master Setup', 'Stock Operations', 'Sales', 'Reports')]
            for key in operational_pages:
                actions = ['view', 'create', 'edit']
                if key in ('shipments', 'gate_pass'):
                    actions.append('delete')
                grant(manager_group, key, actions)
            self.stdout.write(self.style.SUCCESS('Created "Manager" -- broad operational access, no System access except Audit Log (view).'))
        else:
            self.stdout.write('Skip "Manager" (already exists) -- left untouched.')

        # ── HR Officer / Payroll Officer / Viewer: view-only across
        #    operational pages, no System access at all. Deliberately
        #    identical to each other as a starting point -- these are
        #    safety-net defaults, not a considered policy for any of the
        #    three, and each is independently editable from here. ──
        for role_name in ('HR Officer', 'Payroll Officer', 'Viewer'):
            group, created = Group.objects.get_or_create(name=role_name)
            if created:
                operational_pages = [key for key, label, module_group, url_name, order in PAGE_REGISTRY_SEED
                                      if module_group in ('Master Setup', 'Stock Operations', 'Sales', 'Reports')]
                for key in operational_pages:
                    grant(group, key, ['view'])
                self.stdout.write(self.style.SUCCESS(f'Created "{role_name}" -- view-only on operational pages, no System access.'))
            else:
                self.stdout.write(f'Skip "{role_name}" (already exists) -- left untouched.')

        self.stdout.write(self.style.SUCCESS(
            '\nBaseline roles ready. Every grant above is a starting point, not a fixed '
            'policy -- adjust any of it immediately from Role Management.'
        ))
