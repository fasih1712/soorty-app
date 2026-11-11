"""
One-time cleanup for the dual-password issue: any account that has a
datatex_user_id set should never have a working local password (that's
the whole point of the security fix), but accounts mapped BEFORE this
change was in place still have their old local password hash sitting
in the database. This finds exactly those accounts and invalidates it.

Scope is deliberately narrow and explicit: ONLY touches accounts where
datatex_user_id is set. Every local-only account (including your two
existing non-Datatex accounts) is left completely untouched -- this
command never even looks at them.

Safe to run more than once: an account whose password is already
unusable is skipped and reported separately, not re-processed.

Usage:
    python manage.py lock_datatex_mapped_local_passwords --dry-run
    python manage.py lock_datatex_mapped_local_passwords
"""
from django.core.management.base import BaseCommand
from apps.accounts.models import CustomUser


class Command(BaseCommand):
    help = (
        "Sets an unusable local password on every account that has a "
        "datatex_user_id set. Never touches accounts without one."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would change without saving anything.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        mapped_users = CustomUser.objects.exclude(
            datatex_user_id__isnull=True
        ).exclude(datatex_user_id__exact='')

        already_unusable = 0
        to_fix = []
        for user in mapped_users:
            if user.has_usable_password():
                to_fix.append(user)
            else:
                already_unusable += 1

        self.stdout.write(f"Datatex-mapped accounts found: {mapped_users.count()}")
        self.stdout.write(f"  Already unusable (no action needed): {already_unusable}")
        self.stdout.write(f"  Have a working local password (will be locked): {len(to_fix)}")

        if not to_fix:
            self.stdout.write(self.style.SUCCESS("Nothing to do."))
            return

        for user in to_fix:
            self.stdout.write(f"  - {user.username} (datatex_user_id={user.datatex_user_id})")

        if dry_run:
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN -- no changes saved. Re-run without --dry-run to apply."
            ))
            return

        for user in to_fix:
            user.set_unusable_password()
            user.save(update_fields=['password'])

        self.stdout.write(self.style.SUCCESS(
            f"\nDone -- {len(to_fix)} account(s) locked to Datatex-only authentication."
        ))
