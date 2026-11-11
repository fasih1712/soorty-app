"""
One-time migration: converts every existing wst_djn_sales row (+ its
wst_djn_sale_items line, if any) into the new wst_djn_sales_header /
wst_djn_sales_line tables.

IMPORTANT — this does NOT touch the stock ledger or item balance.
Every legacy sale already posted its OUT entry to wst_djn_stock_ledger at
the moment it was originally created (the old insert_sale() always posted
immediately, regardless of status). Re-deriving new ledger postings during
this migration would DOUBLE-COUNT that stock movement. This command only
creates the header/line records that faithfully mirror what already
happened historically — the ledger and balance data are left exactly as
they are.

STATUS MAPPING: the old system never actually reversed the ledger when a
sale's status was set to a cancelled-looking value (update_sale() only ever
touched the STATUS string column, nothing else) — so a migrated row is
marked CANCELLED here only to preserve that historical label, not because
any reversal is being applied now. Everything else becomes POSTED, since
its real-world stock effect has already happened.

Safe to re-run: each migrated header stores the original SALE_ID in
legacy_sale_id, and any sale already carrying that legacy_sale_id is
skipped on subsequent runs.

Usage:
    python manage.py migrate_legacy_sales           # migrate everything not yet migrated
    python manage.py migrate_legacy_sales --dry-run # show what WOULD happen, change nothing
"""
from django.core.management.base import BaseCommand
from apps.wastage.oracle_data import get_connection
from datetime import date


CANCELLED_LABELS = {'CANCELLED', 'CANCEL', 'VOID', 'VOIDED'}


class Command(BaseCommand):
    help = "Migrate legacy wst_djn_sales/wst_djn_sale_items rows into wst_djn_sales_header/wst_djn_sales_line"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                             help="Show what would be migrated without writing anything")

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        with get_connection('migrate_legacy_sales') as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT s.SALE_ID, NVL(s.DIVISION,'08') AS DIVISION, s.VENDOR_ID,
                           TO_CHAR(s.SALE_DATE,'YYYY-MM-DD') AS SALE_DATE,
                           s.INVOICE_NO, s.STATUS, s.TOTAL_AMOUNT
                    FROM wst_djn_sales s
                    WHERE NOT EXISTS (
                        SELECT 1 FROM wst_djn_sales_header h WHERE h.LEGACY_SALE_ID = s.SALE_ID
                    )
                    ORDER BY s.SALE_DATE, s.SALE_ID
                """)
                legacy_sales = cur.fetchall()

                if not legacy_sales:
                    self.stdout.write(self.style.SUCCESS("Nothing to migrate — all legacy sales already have a header, or none exist."))
                    return

                self.stdout.write(f"Found {len(legacy_sales)} legacy sale(s) to migrate.")

                # Seed the per-year doc_id counter from anything already migrated / created
                cur.execute("SELECT DOC_ID FROM wst_djn_sales_header")
                existing_ids = [r[0] for r in cur.fetchall()]
                year_counters = {}
                for doc_id in existing_ids:
                    try:
                        _, yr, n = doc_id.split('-')
                        year_counters[yr] = max(year_counters.get(yr, 0), int(n))
                    except (ValueError, AttributeError):
                        continue

                migrated, skipped_no_items = 0, 0

                for sale_id, division, vendor_id, sale_date, invoice_no, status, total_amount in legacy_sales:
                    yr = sale_date[:4] if sale_date else str(date.today().year)
                    year_counters[yr] = year_counters.get(yr, 0) + 1
                    doc_id = f"DOC-{yr}-{year_counters[yr]:04d}"

                    new_status = 'CANCELLED' if (status or '').strip().upper() in CANCELLED_LABELS else 'POSTED'

                    cur.execute("""SELECT ITEM_ID, QTY_SOLD, RATE FROM wst_djn_sale_items WHERE SALE_ID=:1""",
                                [sale_id])
                    items = cur.fetchall()
                    if not items:
                        skipped_no_items += 1
                        self.stdout.write(self.style.WARNING(
                            f"  SALE_ID {sale_id}: no wst_djn_sale_items row found — migrating header only, no lines."))

                    self.stdout.write(
                        f"  SALE_ID {sale_id} -> {doc_id} (div {division}, {new_status}, {len(items)} line(s))")

                    if dry_run:
                        migrated += 1
                        continue

                    cur.execute("""INSERT INTO wst_djn_sales_header
                        (DOC_ID, DIVISION, VENDOR_ID, DOC_DATE, INVOICE_NO, STATUS,
                         TOTAL_AMOUNT, LEGACY_SALE_ID, CREATED_DATE, POSTED_DATE)
                        VALUES (:1,:2,:3,TO_DATE(:4,'YYYY-MM-DD'),:5,:6,:7,:8,SYSDATE,
                                CASE WHEN :6 = 'POSTED' THEN SYSDATE ELSE NULL END)""",
                        [doc_id, str(division), vendor_id, sale_date, invoice_no,
                         new_status, float(total_amount or 0), sale_id])

                    line_no = 10
                    for item_id, qty_sold, rate in items:
                        cur.execute("""INSERT INTO wst_djn_sales_line
                            (DOC_ID, LINE_NO, ITEM_ID, QUANTITY, UNIT_PRICE)
                            VALUES (:1,:2,:3,:4,:5)""",
                            [doc_id, line_no, item_id, float(qty_sold or 0), float(rate or 0)])
                        line_no += 10

                    migrated += 1

                if dry_run:
                    conn.rollback()
                    self.stdout.write(self.style.WARNING(
                        f"\nDRY RUN — would migrate {migrated} sale(s) ({skipped_no_items} with no line items). Nothing written."))
                else:
                    conn.commit()
                    self.stdout.write(self.style.SUCCESS(
                        f"\nMigrated {migrated} sale(s) ({skipped_no_items} with no line items). Ledger/balance data untouched."))
