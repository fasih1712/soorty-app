"""
python manage.py map_users_to_roles

Adds every existing user to the baseline Group matching their legacy
`role` field (admin -> Administrator, manager -> Manager, hr -> HR
Officer, payroll -> Payroll Officer, viewer -> Viewer), so no account
is left with zero Group membership once enforcement is live everywhere.

Additive only: never removes a user from a Group they're already in
(so anything already customized by hand is left alone), and never
touches is_superuser. Safe to run repeatedly.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group

from apps.accounts.models import CustomUser

ROLE_TO_GROUP = {
    'admin': 'Administrator',
    'manager': 'Manager',
    'hr': 'HR Officer',
    'payroll': 'Payroll Officer',
    'viewer': 'Viewer',
}


class Command(BaseCommand):
    help = "Map every existing user's legacy role field onto the matching baseline Group."

    def handle(self, *args, **options):
        mapped = 0
        skipped_no_group = 0
        already_had_a_group = 0

        for user in CustomUser.objects.all():
            if user.groups.exists():
                already_had_a_group += 1
                continue
            group_name = ROLE_TO_GROUP.get(user.role)
            if not group_name:
                skipped_no_group += 1
                continue
            try:
                group = Group.objects.get(name=group_name)
            except Group.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f'"{group_name}" doesn\'t exist yet -- run seed_baseline_roles first. Skipping {user.username}.'
                ))
                continue
            user.groups.add(group)
            mapped += 1
            self.stdout.write(f'  {user.username} (role={user.role}) -> {group_name}')

        self.stdout.write(self.style.SUCCESS(
            f'\n{mapped} user(s) mapped. {already_had_a_group} already had a Group and were left untouched. '
            f'{skipped_no_group} had no recognized legacy role value and were skipped.'
        ))
        if skipped_no_group:
            self.stdout.write(self.style.WARNING(
                'Any skipped users have no Group at all and will be locked out everywhere except what '
                'superuser status would grant -- check them manually in User Management.'
            ))
