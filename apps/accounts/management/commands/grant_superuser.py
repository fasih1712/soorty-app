"""
python manage.py grant_superuser <username>

Marks one user as a Django superuser -- the one thing that bypasses
every RBAC check outright (see has_page_permission() in rbac.py). This
exists because the RBAC system has a standard "bootstrap" problem: once
enforcement is live, SOMEONE needs a way in before any Role has been
configured with real permissions. Superuser is the Django-idiomatic
answer to that, and is intentionally kept separate from this app's own
legacy `role` field, which is cosmetic only.

Use this to unblock the first real administrator account. Once Roles
are configured with the permissions your team reviews and approves, you
can choose to keep using superuser for a small number of trusted
accounts, or move them onto an "Administrator" Role instead -- either
works, since has_page_permission() checks superuser first and would
short-circuit to True regardless of Role membership.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import CustomUser


class Command(BaseCommand):
    help = "Grant Django superuser status to one user, bypassing all RBAC checks."

    def add_arguments(self, parser):
        parser.add_argument('username', type=str)
        parser.add_argument('--revoke', action='store_true', help='Remove superuser status instead of granting it.')

    def handle(self, *args, **options):
        username = options['username']
        try:
            user = CustomUser.objects.get(username=username)
        except CustomUser.DoesNotExist:
            raise CommandError(f'No user found with username "{username}".')

        if options['revoke']:
            user.is_superuser = False
            user.is_staff = False
            user.save()
            self.stdout.write(self.style.SUCCESS(f'Revoked superuser status from "{username}".'))
        else:
            user.is_superuser = True
            user.is_staff = True  # also allows Django Admin access, harmless and conventional alongside superuser
            user.save()
            self.stdout.write(self.style.SUCCESS(
                f'"{username}" is now a superuser -- full access to every page and action, '
                f'independent of any Role or override.'
            ))
