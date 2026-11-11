from apps.wastage.oracle_data import get_connection
conn = get_connection()
cur = conn.cursor()
cur.execute("SELECT STATUS, COUNT(*) FROM wst_djn_sales_header WHERE TRUNC(DOC_DATE,'MM') = TO_DATE('2026-09-01','YYYY-MM-DD') GROUP BY STATUS ORDER BY STATUS")
print('Breakdown of Sep 2026 by status:', cur.fetchall())
cur.execute("SELECT COUNT(*) FROM wst_djn_sales_header WHERE STATUS='CLOSED' AND TRUNC(DOC_DATE,'MM') = TO_DATE('2026-09-01','YYYY-MM-DD')")
print('Of those, how many are Closed:', cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM wst_djn_sales_header WHERE STATUS='CLOSED' AND TRUNC(DOC_DATE,'MM') != TO_DATE('2026-09-01','YYYY-MM-DD')")
print('Closed sales from months OTHER than Sep 2026:', cur.fetchone()[0])

