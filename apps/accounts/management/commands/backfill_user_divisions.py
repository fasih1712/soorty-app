"""
Step 1 of the multi-division migration (see Division's docstring in
models.py for the full staged plan): seeds the new Division reference
table from the legacy DIVISION_CHOICES list, then gives every existing
user's new `divisions` (plural) field the same single division their
old `division` (singular) field already has -- so after this runs,
both fields agree, and multi-division access can be layered on top by
adding more divisions per user afterward, through the (still to be
built) User Management UI.

Safe to run more than once: Division rows are get_or_create'd by code,
and a user already holding the correct division in `divisions` is left
alone rather than duplicated.

Usage:
    python manage.py backfill_user_divisions [--dry-run]
"""
from django.core.management.base import BaseCommand
from apps.accounts.models import CustomUser, Division


class Command(BaseCommand):
    help = "Seeds the Division table and backfills every user's divisions (M2M) from their legacy division field."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Report what would change without writing anything.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        # --- Step A: seed Division rows from the legacy choices list ---
        divisions_created = 0
        code_to_division = {}
        valid_codes = {code for code, _ in CustomUser.DIVISION_CHOICES}
        for order, (code, name) in enumerate(CustomUser.DIVISION_CHOICES):
            if dry_run:
                existing = Division.objects.filter(code=code).first()
                if not existing:
                    divisions_created += 1
                    self.stdout.write(f'  WOULD CREATE Division {code} — {name}')
                # In dry-run, code_to_division is used only to report
                # what Step B *would* do -- it intentionally does NOT
                # need a real Division row to do that, since Step A's
                # creation hasn't (and won't) actually happen yet.
            else:
                division, created = Division.objects.get_or_create(
                    code=code, defaults={'name': name, 'display_order': order},
                )
                if created:
                    divisions_created += 1
                    self.stdout.write(f'  OK    Division {code} — {name} created')
                code_to_division[code] = division

        if not dry_run:
            self.stdout.write(f'Divisions: {divisions_created} created, {len(CustomUser.DIVISION_CHOICES) - divisions_created} already existed.')
        else:
            self.stdout.write(f'Divisions: {divisions_created} would be created (dry run — nothing written).')

        # --- Step B: backfill every user's divisions (M2M) from division (legacy single value) ---
        users_updated = 0
        users_already_correct = 0
        users_skipped_unknown_code = 0

        for user in CustomUser.objects.all():
            if user.division not in valid_codes:
                # A division code on the user that isn't in the current
                # DIVISION_CHOICES list at all -- flagged, not silently
                # skipped, since it means this user's data needs a
                # manual look rather than a guess.
                users_skipped_unknown_code += 1
                self.stdout.write(self.style.WARNING(
                    f'  SKIP  {user.username}: division={user.division!r} has no matching Division row'
                ))
                continue

            if dry_run:
                # No real Division row exists yet to check the M2M
                # against in dry-run mode -- reported as "would add"
                # unconditionally, which is accurate for a first run;
                # a second dry-run after divisions genuinely exist
                # would need the real-run branch below to see anything
                # already correct, which is exactly what happens once
                # this is actually applied.
                users_updated += 1
                self.stdout.write(f'  WOULD ADD {user.username}: divisions += {user.division}')
            else:
                target = code_to_division[user.division]
                if user.divisions.filter(pk=target.pk).exists():
                    users_already_correct += 1
                else:
                    user.divisions.add(target)
                    users_updated += 1

        verb = 'would be updated' if dry_run else 'updated'
        self.stdout.write(self.style.SUCCESS(
            f'Users: {users_updated} {verb}, {users_already_correct} already correct, '
            f'{users_skipped_unknown_code} skipped (unknown division code).'
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run -- nothing was actually written. Re-run without --dry-run to apply.'))
