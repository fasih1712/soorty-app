from django.db import connection
with connection.cursor() as cur:
    cur.execute("SELECT PRIVILEGE FROM USER_SYS_PRIVS WHERE PRIVILEGE = 'CREATE SEQUENCE'")
    print('CREATE SEQUENCE VISIBLE TO THIS CONNECTION:', cur.fetchall())

