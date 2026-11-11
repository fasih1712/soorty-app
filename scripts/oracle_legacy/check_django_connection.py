from django.db import connection
with connection.cursor() as cur:
    cur.execute("SELECT USER FROM DUAL")
    print('DJANGO IS ACTUALLY CONNECTED AS:', cur.fetchone())
    cur.execute("SELECT PRIVILEGE FROM USER_SYS_PRIVS WHERE PRIVILEGE = 'CREATE TABLE'")
    print('CREATE TABLE VISIBLE TO THIS CONNECTION:', cur.fetchall())

