"""
One-time backfill: populates item_code for every existing wst_djn_items
row that doesn't have one yet, following the Smart Structured Item Code
standard (CATEGORY_PREFIX-SUB_SPEC-SEQUENCE).

Six items have their EXACT target codes hardcoded below, taken directly
from the SRS's own worked examples -- these are guaranteed to match
exactly, not derived. Every other existing item gets a code computed by
the same derive_sub_spec_code() logic used for new item creation, with
sequence numbers assigned in item_id order within each category (so the
six hardcoded items' sequence positions are respected and everything
else fills in around them without collisions).

IMPORTANT: derive_sub_spec_code() is a consistent, documented algorithm,
not a perfect reverse-engineering of the hand-picked examples -- see the
docstring on that function in oracle_data.py. For the 22 items NOT
explicitly listed in the SRS, this will produce reasonable, predictable
codes, but they won't necessarily match an ad-hoc human abbreviation
style for every item. Review the generated codes after running and let
me know if specific ones should be corrected.

Safe to re-run: only items with a NULL item_code are touched.

Usage:
    python manage.py backfill_item_codes           # apply
    python manage.py backfill_item_codes --dry-run # show what WOULD happen, change nothing
"""
from django.core.management.base import BaseCommand
from apps.wastage.oracle_data import get_connection, derive_sub_spec_code

# Exact target codes from the SRS's own worked examples, keyed by ITEM_ID.
HARDCODED_CODES = {
    10040: 'BW-SZ-001',
    10041: 'BW-SZR-002',
    10042: 'BW-LL-003',
    10048: 'DR-P050-001',
    10049: 'DR-P120-002',
    10054: 'DM-OU-001',
}


class Command(BaseCommand):
    help = 'Backfill item_code for all existing items using the Smart Structured Item Code standard.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show what would happen without changing anything.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT i.ITEM_ID, i.ITEM_NAME, i.CATEGORY_ID, c.CATEGORY_NAME, c.PREFIX, i.ITEM_CODE
                    FROM wst_djn_items i LEFT JOIN wst_djn_categories c ON i.CATEGORY_ID = c.CATEGORY_ID
                    ORDER BY i.CATEGORY_ID, i.ITEM_ID""")
                cols = [c[0] for c in cur.description]
                items = [dict(zip(cols, row)) for row in cur.fetchall()]

                pending = [i for i in items if not i['ITEM_CODE']]
                if not pending:
                    self.stdout.write(self.style.SUCCESS('Nothing to do -- every item already has an item_code.'))
                    return

                # Running per-category sequence counter, in item_id order,
                # covering EVERY item in that category (not just the
                # pending ones) so hardcoded items' sequence positions are
                # correctly reserved and nothing collides.
                seq_by_category = {}
                updates = []
                missing_prefix_categories = set()

                for item in items:
                    cat_id = item['CATEGORY_ID']
                    seq_by_category[cat_id] = seq_by_category.get(cat_id, 0) + 1
                    if item['ITEM_CODE']:
                        continue  # already has a code -- don't touch, but its sequence slot is still counted above

                    item_id = item['ITEM_ID']
                    if item_id in HARDCODED_CODES:
                        code = HARDCODED_CODES[item_id]
                    else:
                        prefix = item['PREFIX']
                        if not prefix:
                            missing_prefix_categories.add(item['CATEGORY_NAME'] or f'(category {cat_id})')
                            prefix = 'GEN'
                        sub_spec = derive_sub_spec_code(item['ITEM_NAME'], item['CATEGORY_NAME'] or '')
                        seq = seq_by_category[cat_id]
                        code = f"{prefix}-{sub_spec}-{seq:03d}" if sub_spec else f"{prefix}-{seq:03d}"
                    updates.append((item_id, item['ITEM_NAME'], item['CATEGORY_NAME'], code))

                self.stdout.write(f'{len(updates)} item(s) will be updated:\n')
                for item_id, name, cat_name, code in updates:
                    self.stdout.write(f'  #{item_id:<8} {cat_name or "(no category)":<25} {name:<40} -> {code}')

                if missing_prefix_categories:
                    self.stdout.write(self.style.WARNING(
                        f"\nWARNING: these categories have no PREFIX set yet, so 'GEN' was used as a "
                        f"placeholder -- set a real prefix on them and re-run to correct: "
                        f"{', '.join(sorted(missing_prefix_categories))}"
                    ))

                if dry_run:
                    self.stdout.write(self.style.WARNING('\n--dry-run: no changes were made.'))
                    return

                for item_id, name, cat_name, code in updates:
                    cur.execute("UPDATE wst_djn_items SET ITEM_CODE=:1 WHERE ITEM_ID=:2", [code, item_id])
                conn.commit()
                self.stdout.write(self.style.SUCCESS(f'\nDone -- {len(updates)} item(s) updated.'))
