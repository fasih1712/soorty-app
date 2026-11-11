from apps.wastage.oracle_data import get_connection

with get_connection() as conn:
    cur = conn.cursor()
    cur.execute("""SELECT TRIGGER_NAME, TRIGGERING_EVENT, STATUS FROM USER_TRIGGERS
        WHERE TABLE_NAME = 'WST_DJN_ITEM_BALANCE'""")
    print('Triggers on wst_djn_item_balance:', cur.fetchall())

    cur.execute("SELECT SEQUENCE_NAME, LAST_NUMBER FROM USER_SEQUENCES WHERE SEQUENCE_NAME LIKE '%ITEM_BAL%'")
    print('Matching sequences:', cur.fetchall())

    cur.execute("""SELECT COLUMN_NAME, DATA_DEFAULT FROM USER_TAB_COLUMNS
        WHERE TABLE_NAME = 'WST_DJN_ITEM_BALANCE' AND COLUMN_NAME = 'BALANCE_ID'""")
    print('BALANCE_ID column default:', cur.fetchall())

    cur.execute("SELECT NVL(MAX(BALANCE_ID),0) FROM wst_djn_item_balance")
    next_id = cur.fetchone()[0] + 1
    print('Next BALANCE_ID to use:', next_id)

    cur.execute("""INSERT INTO wst_djn_item_balance
        (BALANCE_ID, ITEM_ID, DIVISION, TOTAL_IN, TOTAL_OUT, BALANCE, LAST_TXN_DATE, LAST_TXN_TYPE, LAST_TXN_QTY)
        SELECT :1, ITEM_ID, NVL(DIVISION,'08'), NVL(SUM(QTY_IN),0), NVL(SUM(QTY_OUT),0), NVL(SUM(QTY_IN),0)-NVL(SUM(QTY_OUT),0),
               MAX(TXN_DATE), MAX(TXN_TYPE) KEEP (DENSE_RANK LAST ORDER BY TXN_DATE), NULL
        FROM wst_djn_stock_ledger WHERE ITEM_ID = 10209 AND NVL(DIVISION,'08') = '08'
        GROUP BY ITEM_ID, NVL(DIVISION,'08')""", [next_id])
    conn.commit()
    print('Inserted the missing balance row for Sludge Oil (item 10209)')

    cur.execute("SELECT * FROM wst_djn_item_balance WHERE ITEM_ID = 10209")
    cols = [c[0] for c in cur.description]
    print('Confirmed row now exists:', dict(zip(cols, cur.fetchone())))

