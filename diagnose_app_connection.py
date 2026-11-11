from apps.wastage.oracle_data import get_connection
with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT SYS_CONTEXT('USERENV','DB_NAME'), SYS_CONTEXT('USERENV','HOST'), SYS_CONTEXT('USERENV','SERVICE_NAME') FROM DUAL")
        print('APP IS ACTUALLY CONNECTED TO:', cur.fetchone())
        cur.execute("SELECT DOC_ID, STATUS FROM wst_djn_sales_header WHERE DOC_ID IN ('DOC-2026-0003','DOC-2026-0001')")
        print('APP SEES THESE ROWS AS:', cur.fetchall())

