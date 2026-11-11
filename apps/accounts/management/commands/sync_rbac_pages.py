"""
python manage.py sync_rbac_pages

Seeds/updates PageRegistry from the canonical PAGE_REGISTRY_SEED list in
apps/accounts/rbac.py, and ensures each page's four Django Permission
objects (view/create/edit/delete) exist. Safe to run repeatedly: new
pages are added, existing ones are updated in place (label, module
group, url_name, ordering), and nothing already in the database is
deleted -- pages removed from the seed list are left in the database
(so historical permission/override records tied to them aren't
orphaned) but should be marked is_active=False by hand if truly
retired, which excludes them from has_page_permission() checks and the
matrix UI without losing that history.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.rbac import PAGE_REGISTRY_SEED, sync_permissions_for_page


class Command(BaseCommand):
    help = "Seed/sync PageRegistry and its Permission objects from the canonical page list."

    def handle(self, *args, **options):
        from apps.accounts.models import PageRegistry

        created_pages = 0
        updated_pages = 0
        created_permissions = 0

        with transaction.atomic():
            for key, label, module_group, url_name, display_order in PAGE_REGISTRY_SEED:
                page, created = PageRegistry.objects.get_or_create(
                    key=key,
                    defaults={
                        'label': label, 'module_group': module_group,
                        'url_name': url_name, 'display_order': display_order,
                    },
                )
                if created:
                    created_pages += 1
                else:
                    # Keep the DB in step with the code-side seed for anything
                    # that legitimately changes (a relabel, a re-grouping, a
                    # reordering) -- but never touch is_active, since that's
                    # an operational decision made in the UI, not something
                    # the seed list should silently override.
                    changed = False
                    for field, value in [('label', label), ('module_group', module_group),
                                          ('url_name', url_name), ('display_order', display_order)]:
                        if getattr(page, field) != value:
                            setattr(page, field, value)
                            changed = True
                    if changed:
                        page.save()
                        updated_pages += 1

                created_permissions += sync_permissions_for_page(page)

        self.stdout.write(self.style.SUCCESS(
            f'Pages: {created_pages} created, {updated_pages} updated, '
            f'{len(PAGE_REGISTRY_SEED)} total in seed. '
            f'Permissions: {created_permissions} newly created.'
        ))
