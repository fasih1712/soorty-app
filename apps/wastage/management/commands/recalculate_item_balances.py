"""
One-time (but safe to re-run) repair: recalculates wst_djn_item_balance
for every item+division combination that has any Stock Ledger activity.

Why this is needed: a bug in _recalc_item_balance() silently failed to
update Item Balance every time a Sales document was Ship & Posted (the
Stock Ledger itself was always correct -- only the Item Balance summary
was affected). That's now fixed going forward, but it does NOT
retroactively correct any Item Balance row that was already left wrong
by a past Sale, if that item hasn't since had a Shipment Cancellation or
Sales Order Cancellation to accidentally "catch it up". This command
recalculates every affected item's Total In / Total Out / Balance fresh
from the Stock Ledger, which is the source of truth and was never wrong.

Safe to re-run any time -- it's a full, idempotent recalculation, not an
incremental adjustment, so running it twice in a row produces the same
result as running it once.

Usage:
    python manage.py recalculate_item_balances                    # every item, every division
    python manage.py recalculate_item_balances --item-id 47        # one item, all its divisions
    python manage.py recalculate_item_balances --division 08       # one division, all items
"""
from django.core.management.base import BaseCommand
from apps.wastage.oracle_data import recalculate_all_balances


class Command(BaseCommand):
    help = "Recalculate Item Balance (Total In/Out/Balance) from the Stock Ledger for every item+division, fixing rows left wrong by the Sale-posting datetime bug."

    def add_arguments(self, parser):
        parser.add_argument('--item-id', type=int, default=None,
                             help='Only recalculate this item (all its divisions). Omit to recalculate every item.')
        parser.add_argument('--division', type=str, default=None,
                             help='Only recalculate this division (all its items). Omit to recalculate every division.')

    def handle(self, *args, **options):
        item_id = options['item_id']
        division = options['division']
        scope = []
        if item_id:
            scope.append(f'item {item_id}')
        if division:
            scope.append(f'division {division}')
        scope_desc = ' and '.join(scope) if scope else 'every item, every division'

        self.stdout.write(f'Recalculating Item Balance for {scope_desc} from the Stock Ledger...')
        try:
            recalculate_all_balances(item_id=item_id, division=division)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Failed: {e}'))
            return
        self.stdout.write(self.style.SUCCESS('Done. Item Balance now matches the Stock Ledger for the selected scope.'))
