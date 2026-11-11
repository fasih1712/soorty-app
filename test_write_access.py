"""
Run directly on the app server:  python test_write_access.py

Tests INSERT/UPDATE/DELETE against a real table the app actually writes
to (WST_DJN_AUDIT_LOG -- append-only, low-stakes, exactly the kind of
row this table is meant to hold anyway) -- but everything happens
inside one transaction that gets ROLLED BACK at the end, never
committed. No trace is left in the database either way, success or
failure.
"""
import os
import oracledb

DB_USER = os.environ.get("DB_USER", "")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_HOST = os.environ.get("DB_HOST", "")
DB_PORT = int(os.environ.get("DB_PORT", "1521"))
DB_SERVICE = os.environ.get("DB_SERVICE_NAME", "")

dsn = oracledb.makedsn(DB_HOST, DB_PORT, service_name=DB_SERVICE)
conn = oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=dsn)
cur = conn.cursor()

test_record_id = "WRITE_ACCESS_TEST_DO_NOT_KEEP"

try:
    cur.execute(
        """INSERT INTO wst_djn_audit_log
           (TABLE_NAME, RECORD_ID, ACTION, FIELD_NAME, NEW_VALUE, CHANGED_BY)
           VALUES ('TEST', :1, 'INSERT', 'test_field', 'test_value', 'write_access_test')""",
        [test_record_id],
    )
    print("INSERT OK")

    cur.execute(
        "UPDATE wst_djn_audit_log SET NEW_VALUE = 'updated_value' WHERE RECORD_ID = :1",
        [test_record_id],
    )
    print("UPDATE OK")

    cur.execute("DELETE FROM wst_djn_audit_log WHERE RECORD_ID = :1", [test_record_id])
    print("DELETE OK")

    print("\nALL WRITE OPERATIONS SUCCEEDED -- apxWastage has full DML access.")

except Exception as e:
    print(f"\nWRITE TEST FAILED: {e}")
    print("This IS a real gap -- apxWastage can read but not write (or not "
          "this particular operation). Re-run 04_grant_apxwastage.sql "
          "connected as APXPROD/DBA, not as apxWastage.")

finally:
    conn.rollback()
    print("\nTransaction rolled back -- no data was actually changed, "
          "regardless of the result above.")
    conn.close()
