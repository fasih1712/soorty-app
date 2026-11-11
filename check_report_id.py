from apps.wastage.oracle_data import get_connection
conn = get_connection()
cur = conn.cursor()
cur.execute("SELECT SEQUENCE_NAME FROM USER_SEQUENCES WHERE SEQUENCE_NAME LIKE '%STOCK_BAL_REPORT%' OR SEQUENCE_NAME LIKE '%REPORT_ID%'")
print('Matching sequences:', cur.fetchall())
cur.execute("SELECT COLUMN_NAME, DATA_DEFAULT FROM USER_TAB_COLUMNS WHERE TABLE_NAME = 'WST_DJN_STOCK_BAL_REPORT_LOG' AND COLUMN_NAME = 'REPORT_ID'")
print('REPORT_ID column default:', cur.fetchall())
cur.execute("SELECT NVL(MAX(REPORT_ID),0) FROM wst_djn_stock_bal_report_log")
print('Current MAX(REPORT_ID):', cur.fetchone()[0])

