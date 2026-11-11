from apps.wastage.oracle_data import get_connection, recalculate_all_balances

with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT ITEM_ID, ITEM_NAME FROM wst_djn_items WHERE UPPER(ITEM_NAME) LIKE '%SLUDGE%'")
        items = cur.fetchall()
        print('Matching items:', items)

        for item_id, item_name in items:
            cur.execute("SELECT ITEM_ID, DIVISION, TOTAL_IN, TOTAL_OUT, BALANCE FROM wst_djn_item_balance WHERE ITEM_ID = :1", [item_id])
            print(f'  item_balance rows for {item_name} (ID {item_id}):', cur.fetchall())

            cur.execute("""SELECT NVL(SUM(QTY_IN),0), NVL(SUM(QTY_OUT),0), NVL(SUM(QTY_IN),0)-NVL(SUM(QTY_OUT),0)
                FROM wst_djn_stock_ledger WHERE ITEM_ID = :1""", [item_id])
            print(f'  actual ledger totals for {item_name}:', cur.fetchone())

print()
print('=== Now fixing: recalculating balance for each matching item, Division 08 ===')
for item_id, item_name in items:
    recalculate_all_balances(item_id=item_id, division='08')
    print(f'  recalculated for {item_name} (ID {item_id})')

print()
print('=== Re-checking after fix ===')
with get_connection() as conn:
    with conn.cursor() as cur:
        for item_id, item_name in items:
            cur.execute("SELECT ITEM_ID, DIVISION, TOTAL_IN, TOTAL_OUT, BALANCE FROM wst_djn_item_balance WHERE ITEM_ID = :1", [item_id])
            print(f'  item_balance rows for {item_name} (ID {item_id}) NOW:', cur.fetchall())

