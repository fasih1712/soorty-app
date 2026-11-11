import os
import sys
import environ
import oracledb

# Load environment variables
env = environ.Env()
environ.Env.read_env(os.path.join(os.path.dirname(__file__), ".env"))

db_user = env("DB_USER", default="")
db_password = env("DB_PASSWORD", default="")
db_host = env("DB_HOST", default="")
db_port = env("DB_PORT", default="1521")
db_service = env("DB_SERVICE_NAME", default="")

print("--- STEP 1: Testing Direct DB Connection ---")
try:
    dsn = f"{db_host}:{db_port}/{db_service}"
    conn = oracledb.connect(user=db_user, password=db_password, dsn=dsn)
    print("STEP 1 PASSED: Connected successfully!")
except Exception as e:
    print(f"STEP 1 FAILED: Could not connect to DB -> {e}")
    sys.exit(1)

cursor = conn.cursor()

print("\n--- STEP 2: Checking Current Schema ---")
try:
    cursor.execute(
        "SELECT sys_context('USERENV', 'CURRENT_SCHEMA') FROM dual"
    )
    current_schema = cursor.fetchone()[0]
    print(f"STEP 2 PASSED: Current Schema is '{current_schema}'")
except Exception as e:
    print(f"STEP 2 FAILED: Could not check schema -> {e}")
    sys.exit(1)

print("\n--- STEP 3: Checking Table Visibility ---")
try:
    cursor.execute(
        "SELECT count(*) FROM user_tables WHERE table_name LIKE 'WST_DJN_%'"
    )
    count = cursor.fetchone()[0]
    print(f"STEP 3 PASSED: Found {count} WST_DJN_% tables in view.")
except Exception as e:
    print(f"STEP 3 FAILED: Could not query tables -> {e}")

print("\n--- STEP 4: Querying WST_DJN_GATEPASS_HEADER ---")
try:
    cursor.execute("SELECT count(*) FROM wst_djn_gatepass_header")
    gp_count = cursor.fetchone()[0]
    print(
        f"STEP 4 PASSED: Successfully queried gatepass header ({gp_count} rows)."
    )
except Exception as e:
    print(f"STEP 4 FAILED: Query failed -> {e}")

cursor.close()
conn.close()
print("\n--- ALL DIAGNOSTICS COMPLETE ---")