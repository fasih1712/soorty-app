"""Quick PostgreSQL connectivity check (uses the same settings as the app).

    docker exec -it soorty-app python scripts/check_db.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import db  # noqa: E402

with db.connect('check_db') as conn, conn.cursor() as cur:
    cur.execute("SELECT version(), current_database(), current_user, LOCALTIMESTAMP(0)")
    ver, name, user, now = cur.fetchone()
    print(f"OK  {name} as {user}  ({now})\n    {ver}")
    cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name LIKE 'wst_djn_%'")
    print(f"    wst_djn_* tables: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM wst_djn_fin_account")
    print(f"    finance accounts seeded: {cur.fetchone()[0]}")
